# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)
import json
from odoo import http, models, fields, api, tools, service, modules, _
from odoo.http import request, Response, content_disposition, serialize_exception
import json
from datetime import datetime, time, timedelta
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.service.db import list_dbs
from num2words import num2words
from collections import defaultdict
from PIL import Image
from lxml import etree
from requests.exceptions import ConnectTimeout, ReadTimeout, ConnectionError, SSLError
import os
import psycopg2
import qrcode
import io
import base64

def create_blank_image():
    blank_image = Image.new(mode="RGB", size=(200, 200), color=(255, 255, 255))
    img_bytes = io.BytesIO()
    blank_image.save(img_bytes, format='PNG')
    qr = base64.b64encode(img_bytes.getvalue())
    return qr.decode('utf-8')

def format_tanggal_indo(dt):
    if not dt:
        return ''

    hari = {
        0: 'Senin',
        1: 'Selasa',
        2: 'Rabu',
        3: 'Kamis',
        4: 'Jumat',
        5: 'Sabtu',
        6: 'Minggu',
    }

    bulan = {
        1: 'Januari',
        2: 'Februari',
        3: 'Maret',
        4: 'April',
        5: 'Mei',
        6: 'Juni',
        7: 'Juli',
        8: 'Agustus',
        9: 'September',
        10: 'Oktober',
        11: 'November',
        12: 'Desember',
    }

    return (
        f"{hari[dt.weekday()]}, "
        f"{dt.day} "
        f"{bulan[dt.month]} "
        f"{dt.year}"
    )

class WmsApiController(http.Controller):

    # ---------- Helper: API Key Auth ----------
    def _check_api_key(self):
        api_key = request.httprequest.headers.get('X-API-Key')
        if not api_key:
            return False, _("Missing X-API-Key header")

        expected = request.env['ir.config_parameter'].sudo().get_param('wms.api_key')
        if not expected:
            return False, _("WMS API Key is not configured in System Parameters")

        if api_key != expected:
            return False, _("Invalid API Key")

        return True, None

    def _json_error(self, message, status=400, details=None):
        _logger.warning("WMS API error: %s", message)
        body = {'status': 'error', 'message': message}
        if details:
            body['details'] = details
        return request.make_json_response(body, status=status)

    # =========================================================
    #  POST /wms/api/receiving  -> create inbound / receiving
    # =========================================================
    @http.route('/wms/api/receiving', type='json', auth='public', methods=['POST'], csrf=False)
    def wms_receiving(self, **payload):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_error(err, status=401)

        _logger.info("WMS Receiving payload: %s", payload)

        try:
            Picking = request.env['stock.picking'].sudo()
            Partner = request.env['res.partner'].sudo()
            Product = request.env['product.product'].sudo()
            Location = request.env['stock.location'].sudo()
            Uom = request.env['uom.uom'].sudo()
            Lot = request.env['stock.lot'].sudo()
            PickingType = request.env['stock.picking.type'].sudo()

            external_ref = payload.get('external_ref')
            vendor_code = payload.get('vendor_code')
            vendor_name = payload.get('vendor_name')
            warehouse_code = payload.get('warehouse_code')
            picking_type_code = payload.get('picking_type_code')  # optional
            scheduled_date = payload.get('scheduled_date')
            auto_validate = payload.get('auto_validate', False)
            lines = payload.get('lines')

            if not lines:
                raise UserError(_(f"No lines provided in payload {lines}"))

            # 1) Cari partner
            partner = False
            if vendor_code:
                partner = Partner.search([('ref', '=', vendor_code)], limit=1)
            if not partner and vendor_name:
                partner = Partner.search([('name', '=', vendor_name)], limit=1)
            if not partner:
                raise UserError(_("Vendor not found (vendor_code or vendor_name required)"))

            # 2) Cari picking type (operation_category = 'receive')
            picking_type_domain = [('operation_category', '=', 'receive')]
            if picking_type_code:
                picking_type_domain.append(('sequence_code', '=', picking_type_code))
            picking_type = PickingType.search(picking_type_domain, limit=1)
            if not picking_type:
                raise UserError(_("No picking type configured for operation_category = 'receive'"))

            location_src_id = Location.search([('complete_name', '=', 'Partners/Vendors')], limit=1)
            # 3) Create picking (draft)
            picking_vals = {
                'picking_type_id': picking_type.id,
                'partner_id': partner.id,
                'scheduled_date': scheduled_date,
                'origin': external_ref or payload.get('origin'),
                'location_id': location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
            }

            picking = Picking.create(picking_vals)

            # 4) Create moves
            for line in lines:
                product_code = line.get('product_code')   # default_code / internal reference
                product_barcode = line.get('product_barcode')
                qty = line.get('qty') or line.get('quantity')
                uom_name = line.get('uom')
                lot_name = line.get('lot')
                dest_location_code = line.get('location_dest_code')  # unique_code dari location

                if not product_code and not product_barcode:
                    raise UserError(_("Each line must have product_code or product_barcode"))

                # Cari product
                domain_prod = []
                if product_code:
                    domain_prod = [('default_code', '=', product_code)]
                elif product_barcode:
                    domain_prod = [('barcode', '=', product_barcode)]
                product = Product.search(domain_prod, limit=1)
                if not product:
                    raise UserError(_("Product not found for code/barcode: %s") % (product_code or product_barcode))

                # UoM
                uom = product.uom_id
                if uom_name:
                    uom = Uom.search([('name', '=', uom_name)], limit=1) or product.uom_id

                # Location dest pakai unique_code
                dest_location = picking.location_dest_id
                if dest_location_code:
                    dest_location = Location.search([('complete_name', '=', dest_location_code)], limit=1)
                    if not dest_location:
                        raise UserError(_("Destination location not found for unique_code: %s") % dest_location_code)

                move_vals = {
                    'name': product.display_name,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': dest_location.id,
                }
                move = request.env['stock.move'].sudo().create(move_vals)

                # Lot + immediate done (optional)
                if lot_name:
                    lot = Lot.search([
                        ('name', '=', lot_name),
                        ('product_id', '=', product.id),
                    ], limit=1)
                    if not lot:
                        lot = Lot.create({
                            'name': lot_name,
                            'product_id': product.id,
                        })

                    move_line_vals = {
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_id': uom.id,
                        'qty_done': qty if auto_validate else 0.0,
                        'location_id': picking.location_id.id,
                        'location_dest_id': dest_location.id,
                        'lot_id': lot.id,
                    }
                    request.env['stock.move.line'].sudo().create(move_line_vals)

            # 5) Auto-validate jika diminta (WMS langsung terima)
            if auto_validate:
                picking.action_confirm()
                picking.action_assign()
                picking.button_validate()

            return {
                'status': 'success',
                'picking_id': picking.id,
                'picking_name': picking.name,
                'operation_category': 'receive',
            }

        except UserError as e:
            return self._json_error(str(e), status=400)
        except Exception as e:
            _logger.exception("Unexpected error in /wms/api/receiving")
            return self._json_error(_("Unexpected server error: %s") % str(e), status=500)

    # =========================================================
    #  POST /wms/api/delivery  -> create outbound / DO
    # =========================================================
    @http.route('/wms/api/delivery', type='json', auth='public', methods=['POST'], csrf=False)
    def wms_delivery(self, **kwargs):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_error(err, status=401)

        payload = {}
        _logger.info("WMS Delivery payload: %s", payload)

        try:
            Picking = request.env['stock.picking'].sudo()
            Partner = request.env['res.partner'].sudo()
            Product = request.env['product.product'].sudo()
            Location = request.env['stock.location'].sudo()
            Uom = request.env['uom.uom'].sudo()
            Lot = request.env['stock.lot'].sudo()
            PickingType = request.env['stock.picking.type'].sudo()

            external_ref = payload.get('external_ref')
            customer_code = payload.get('customer_code')
            customer_name = payload.get('customer_name')
            warehouse_code = payload.get('warehouse_code')
            picking_type_code = payload.get('picking_type_code')  # optional
            scheduled_date = payload.get('scheduled_date')
            auto_validate = payload.get('auto_validate', False)
            lines = payload.get('lines') or []

            if not lines:
                raise UserError(_("No lines provided in payload"))

            # 1) Partner
            partner = False
            if customer_code:
                partner = Partner.search([('ref', '=', customer_code)], limit=1)
            if not partner and customer_name:
                partner = Partner.search([('name', '=', customer_name)], limit=1)
            if not partner:
                raise UserError(_("Customer not found (customer_code or customer_name required)"))

            # 2) Picking Type (operation_category = 'delivery')
            picking_type_domain = [('operation_category', '=', 'delivery')]
            if picking_type_code:
                picking_type_domain.append(('sequence_code', '=', picking_type_code))
            picking_type = PickingType.search(picking_type_domain, limit=1)
            if not picking_type:
                raise UserError(_("No picking type configured for operation_category = 'delivery'"))

            location_dest_id = Location.search([('complete_name', '=', 'Partners/Customers')], limit=1)
            # 3) Create picking
            picking_vals = {
                'picking_type_id': picking_type.id,
                'partner_id': partner.id,
                'scheduled_date': scheduled_date,
                'origin': external_ref or payload.get('origin'),
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': location_dest_id.id
            }

            picking = Picking.create(picking_vals)

            # 4) Create moves
            for line in lines:
                product_code = line.get('product_code')
                product_barcode = line.get('product_barcode')
                qty = line.get('qty') or line.get('quantity')
                uom_name = line.get('uom')
                lot_name = line.get('lot')
                src_location_code = line.get('location_src_code')  # unique_code

                if not product_code and not product_barcode:
                    raise UserError(_("Each line must have product_code or product_barcode"))

                # Product
                domain_prod = []
                if product_code:
                    domain_prod = [('default_code', '=', product_code)]
                elif product_barcode:
                    domain_prod = [('barcode', '=', product_barcode)]
                product = Product.search(domain_prod, limit=1)
                if not product:
                    raise UserError(_("Product not found for code/barcode: %s") % (product_code or product_barcode))

                # UoM
                uom = product.uom_id
                if uom_name:
                    uom = Uom.search([('name', '=', uom_name)], limit=1) or product.uom_id

                # Source location pakai unique_code
                src_location = picking.location_id
                if src_location_code:
                    src_location = Location.search([('unique_code', '=', src_location_code)], limit=1)
                    if not src_location:
                        raise UserError(_("Source location not found for unique_code: %s") % src_location_code)

                move_vals = {
                    'name': product.display_name,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id,
                    'picking_id': picking.id,
                    'location_id': src_location.id,
                    'location_dest_id': picking.location_dest_id.id,
                }
                move = request.env['stock.move'].sudo().create(move_vals)

                # Lot + immediate done (optional)
                if lot_name:
                    lot = Lot.search([
                        ('name', '=', lot_name),
                        ('product_id', '=', product.id),
                    ], limit=1)
                    if not lot:
                        lot = Lot.create({
                            'name': lot_name,
                            'product_id': product.id,
                        })

                    move_line_vals = {
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_id': uom.id,
                        'qty_done': qty if auto_validate else 0.0,
                        'location_id': src_location.id,
                        'location_dest_id': picking.location_dest_id.id,
                        'lot_id': lot.id,
                    }
                    request.env['stock.move.line'].sudo().create(move_line_vals)

            # 5) Auto validate (ship langsung)
            if auto_validate:
                picking.action_confirm()
                picking.action_assign()
                picking.button_validate()

            return {
                'status': 'success',
                'picking_id': picking.id,
                'picking_name': picking.name,
                'operation_category': 'delivery',
            }

        except UserError as e:
            return self._json_error(str(e), status=400)
        except Exception as e:
            _logger.exception("Unexpected error in /wms/api/delivery")
            return self._json_error(_("Unexpected server error: %s") % str(e), status=500)


    @http.route('/print/warehouse_receipt', type='http', auth='user')
    def PrintWarehouseReceipt(self, id, **kw):

        receipt = request.env['stock.picking'].sudo().browse(int(id))

        data = {
            'type': receipt.adt_type or '',
            'date': format_tanggal_indo(receipt.scheduled_date),
            'no': receipt.name or '',
            'vendor': receipt.partner_id.name or '',
            'warehouse': '',
            'receipt_date': receipt.scheduled_date.strftime('%Y-%m-%d %H:%M:%S') if receipt.scheduled_date else '',
            'penerima': receipt.location_id.complete_name or '',
            'note': receipt.note_ba or '',
            'detail': []
        }
        for line in receipt.move_ids_without_package:
            obj = {
                'name': line.product_id.display_name or '',
                'uom': line.product_uom.name if line.product_uom.name else '',
                'difference_quantity': float(line.difference_quantity or 0),
                'demand': float(line.product_uom_qty or 0),
                'demand1': float(line.quantity or 0),
                'qty': float(line.quantity or 0),
                'qty2': float(line.product_uom_qty or 0),
                'ket': ''
            }
            data['detail'].append(obj)

        data = json.dumps(data)

        usrnm = 'jasperadmin'
        psswd = 't1j4r1s0lut10n'
        import requests
        execution = requests.post('http://35.194.200.100:8080/jasperserver/rest_v2/reportExecutions',
            auth=(usrnm, psswd),
            json={
                'reportUnitUri': '/Odoo/ADITYA/Penerimaan_Barang',
                'outputFormat': 'pdf',
                'parameters': {
                    'reportParameter': [{
                        'name': 'data',
                        'value': [data]
                    }]
                }
            })
        from lxml import etree
        xml = etree.XML(execution.content)

        try:
            request_id = xml.find('.//requestId').text
            export_id = xml.find('.//export//id').text
            result = requests.get('http://35.194.200.100:8080/jasperserver/rest_v2/reportExecutions/' + request_id + '/exports/' + export_id + '/outputResource', cookies=execution.cookies, verify=False)
            filename = "warehouse_receipt.pdf"
            return request.make_response(result.content, [('Content-Type', result.headers['content-type']), ('Content-Disposition', 'inline; filename=%s;' % filename)])
        except:
            import traceback
            msg = traceback.format_exc()
            request_content = execution.content
            resp = {'msg': msg, 'request_content': str(request_content)}
            resp = json.dumps(resp)
            return request.make_response(resp, [('Content-Type', 'application/json')])

    @http.route('/print/lot_number', type='http', auth='user')
    def PrintLotNumber(self, id, **kw):
        blank_image = create_blank_image()
        lot = request.env['stock.lot'].sudo().browse(int(id))
        data = {
            'lot_name': lot.name or '',
            'product': lot.product_id.name if lot.product_id.name else "",
            'product_code': lot.product_id.default_code if lot.product_id.default_code else "",
            'ref': lot.ref if lot.ref else "",
            'docs': "",
            'date': format_tanggal_indo(fields.Date.today()),
            'qrcode': (lot.qr_code_image.decode('utf-8') if lot.qr_code_image else blank_image),
        #     'detail': []
        }

        data = json.dumps(data)
        usrnm = 'jasperadmin'
        psswd = 't1j4r1s0lut10n'
        import requests
        execution = requests.post('http://35.194.200.100:8080/jasperserver/rest_v2/reportExecutions',
            auth=(usrnm, psswd),
            json={
                'reportUnitUri': '/Odoo/ADITYA/Lot_Number',
                'outputFormat': 'pdf',
                'parameters': {
                    'reportParameter': [{
                        'name': 'data',
                        'value': [data]
                    }]
                }
            })
        from lxml import etree
        xml = etree.XML(execution.content)

        try:
            request_id = xml.find('.//requestId').text
            export_id = xml.find('.//export//id').text
            result = requests.get('http://35.194.200.100:8080/jasperserver/rest_v2/reportExecutions/' + request_id + '/exports/' + export_id + '/outputResource', cookies=execution.cookies, verify=False)
            filename = "warehouse_receipt.pdf"
            return request.make_response(result.content, [('Content-Type', result.headers['content-type']), ('Content-Disposition', 'inline; filename=%s;' % filename)])
        except:
            import traceback
            msg = traceback.format_exc()
            request_content = execution.content
            resp = {'msg': msg, 'request_content': str(request_content)}
            resp = json.dumps(resp)
            return request.make_response(resp, [('Content-Type', 'application/json')])

    @http.route('/print/lot_number_move_line', type='http', auth='user')
    def PrintLotNumberLine(self, ids=None, **kw):

        if not ids:
            return request.make_response(
                json.dumps({'error': 'ids tidak ditemukan'}),
                [('Content-Type', 'application/json')]
            )

        ids = [int(x) for x in ids.split(',') if x]

        lots = request.env['stock.picking'].sudo().browse(ids)

        data = {
            'detail': []
        }

        for move in lots.move_ids_without_package:
            valid_lots = move.lot_ids.filtered(lambda l: l.name)
            if not valid_lots:
                continue
            for lot in valid_lots:
                obj = {
                    'lot_name': lot.name or '',
                    'product': move.product_id.name or '',
                    'product_code': move.product_id.default_code or '',
                    'ref': "",
                    'docs': lots.origin or '',
                    'date': format_tanggal_indo(lots.scheduled_date),
                    'qrcode': (
                        lots.qr_code_image.decode('utf-8')
                        if lots.qr_code_image else blank_image
                    ),
                }
                data['detail'].append(obj)

        data = json.dumps(data)
        usrnm = 'jasperadmin'
        psswd = 't1j4r1s0lut10n'
        import requests
        execution = requests.post('http://35.194.200.100:8080/jasperserver/rest_v2/reportExecutions',
            auth=(usrnm, psswd),
            json={
                'reportUnitUri': '/Odoo/ADITYA/Lot_line',
                'outputFormat': 'pdf',
                'parameters': {
                    'reportParameter': [{
                        'name': 'data',
                        'value': [data]
                    }]
                }
            })
        from lxml import etree
        xml = etree.XML(execution.content)

        try:
            request_id = xml.find('.//requestId').text
            export_id = xml.find('.//export//id').text
            result = requests.get('http://35.194.200.100:8080/jasperserver/rest_v2/reportExecutions/' + request_id + '/exports/' + export_id + '/outputResource', cookies=execution.cookies, verify=False)
            filename = "warehouse_receipt.pdf"
            return request.make_response(result.content, [('Content-Type', result.headers['content-type']), ('Content-Disposition', 'inline; filename=%s;' % filename)])
        except:
            import traceback
            msg = traceback.format_exc()
            request_content = execution.content
            resp = {'msg': msg, 'request_content': str(request_content)}
            resp = json.dumps(resp)
            return request.make_response(resp, [('Content-Type', 'application/json')])