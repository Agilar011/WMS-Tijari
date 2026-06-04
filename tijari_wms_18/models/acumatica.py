import logging
from urllib import response

from odoo import models, fields
import requests
import json
import time
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class StagingTableTMS(models.Model):
    _name = 'staging.table.tms'
    _description = 'Staging Table TMS'
    _rec_name = 'order_no'

    order_no = fields.Char(string='Order No')

    shipment_order_dt = fields.Datetime(
        string='Shipment Order Date'
    )

    shipment_order_type_cd = fields.Char(
        string='Shipment Order Type Code'
    )

    order_state = fields.Char(
        string='Order State'
    )

    distribution_center = fields.Char(
        string='Distribution Center'
    )

    return_branch = fields.Char(
        string='Return Branch'
    )

    package_weight = fields.Float(
        string='Package Weight'
    )

    package_volume = fields.Float(
        string='Package Volume'
    )

    preparation_time = fields.Integer(
        string='Preparation Time'
    )

    payment_type = fields.Char(
        string='Payment Type'
    )

    package_value = fields.Float(
        string='Package Value'
    )

    number_of_items = fields.Integer(
        string='Number of Items'
    )

    partial_delivery_allowed_fl = fields.Char(
        string='Partial Delivery Allowed Flag'
    )

    return_allowed_fl = fields.Char(
        string='Return Allowed Flag'
    )

    cancellation_allowed_fl = fields.Char(
        string='Cancellation Allowed Flag'
    )

    deliver_service_time = fields.Char(
        string='Deliver Service Time'
    )

    deliver_start_time_window = fields.Char(
        string='Deliver Start Time Window'
    )

    deliver_end_time_window = fields.Char(
        string='Deliver End Time Window'
    )

    delivery_type = fields.Char(
        string='Delivery Type'
    )

    deliver_branch = fields.Char(
        string='Deliver Branch'
    )

    deliver_account_code = fields.Char(
        string='Deliver Account Code'
    )

    deliver_account_name = fields.Char(
        string='Deliver Account Name'
    )

    deliver_apartment = fields.Char(
        string='Deliver Apartment'
    )

    deliver_street_name = fields.Char(
        string='Deliver Street Name'
    )

    deliver_locality = fields.Char(
        string='Deliver Locality'
    )

    deliver_city = fields.Char(
        string='Deliver City'
    )

    deliver_state = fields.Char(
        string='Deliver State'
    )

    deliver_country = fields.Char(
        string='Deliver Country'
    )

    deliver_pin_code = fields.Char(
        string='Deliver Pin Code'
    )

    deliver_address_timezone = fields.Char(
        string='Deliver Address Timezone'
    )

    deliver_notes = fields.Text(
        string='Deliver Notes'
    )

    api_sent_datetime = fields.Datetime(
        string='API Sent Date Time'
    )

    crate_ids = fields.One2many(
        'staging.table.tms.crate',
        'shipment_id',
        string='Crates'
    )



    
    def _do_login_tms_api(self):

        url = "https://api.loginextsolutions.com/LoginApp/login/authenticate"

        payload = {
            "userName": "api.tms@aditya.co.id",
            "password": "9CE5Q8Jz_#xXR",
            "sessionExpiryTimeout": "60"
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PostmanRuntime/7.43.0",
        }

        max_retries = 3
        delay_seconds = 30

        for attempt in range(1, max_retries + 1):

            try:

                _logger.info("=== LOGIN TMS API ===")
                _logger.info("Percobaan login ke-%s", attempt)
                _logger.info("URL: %s", url)
                _logger.info("Payload: %s", payload)

                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )

                _logger.info("Response Status: %s", response.status_code)
                _logger.info("Response Text: %s", response.text)

                # Raise error jika status bukan 2xx
                response.raise_for_status()

                # Parse JSON
                try:
                    data = response.json()

                except ValueError:
                    raise UserError(
                        f"Response API bukan JSON:\n{response.text}"
                    )

                _logger.info("Login berhasil pada percobaan ke-%s", attempt)

                return data

            except requests.exceptions.HTTPError as e:

                error_message = (
                    f"HTTP Error {response.status_code}: "
                    f"{response.text}"
                )

                _logger.error(error_message)

            except requests.exceptions.ConnectionError as e:

                error_message = (
                    f"Connection Error: {str(e)}"
                )

                _logger.error(error_message)

            except requests.exceptions.Timeout as e:

                error_message = (
                    f"Timeout Error: {str(e)}"
                )

                _logger.error(error_message)

            except requests.exceptions.RequestException as e:

                error_message = (
                    f"Request Exception: {str(e)}"
                )

                _logger.error(error_message)

            except Exception as e:

                error_message = (
                    f"Unexpected Error: {str(e)}"
                )

                _logger.error(error_message)

            # Jika sudah retry terakhir
            if attempt == max_retries:

                raise UserError(
                    f"Gagal login ke TMS API setelah "
                    f"{max_retries} percobaan.\n\n"
                    f"Error terakhir:\n{error_message}"
                )

            # Delay sebelum retry berikutnya
            _logger.info(
                "Retry login dalam %s detik...",
                delay_seconds
            )

            time.sleep(delay_seconds)    

class StagingTableTMSCrate(models.Model):
    _name = 'staging.table.tms.crate'
    _description = 'Staging Table TMS Crate'
    _rec_name = 'crate_cd'

    crate_cd = fields.Char(
        string='Crate Code'
    )

    crate_name = fields.Char(
        string='Crate Name'
    )

    crate_type = fields.Char(
        string='Crate Type'
    )

    crate_weight = fields.Float(
        string='Crate Weight'
    )

    shipment_id = fields.Many2one(
        'staging.table.tms',
        string='Shipment',
        ondelete='cascade'
    )

    shipment_order_number = fields.Char(
        string='Shipment Order Number'
    )

    line_ids = fields.One2many(
        'staging.table.tms.line',
        'crate_id',
        string='Line Items'
    )


class StagingTableTMSLine(models.Model):
    _name = 'staging.table.tms.line'
    _description = 'Staging Table TMS Line'
    _rec_name = 'item_cd'

    crate_id = fields.Many2one(
        'staging.table.tms.crate',
        string='Crate',
        ondelete='cascade'
    )

    item_cd = fields.Char(
        string='Item Code'
    )

    item_name = fields.Char(
        string='Item Name'
    )

    item_price = fields.Float(
        string='Item Price'
    )

    item_quantity = fields.Integer(
        string='Item Quantity'
    )

    item_type = fields.Char(
        string='Item Type'
    )

    item_weight = fields.Float(
        string='Item Weight'
    )


