from odoo import fields, models


class LoginextStagingData(models.Model):
    _name = "loginext.staging.data"
    _description = "Loginext Staging Data"

    loginext_order_no = fields.Char(string="Order No")
    loginext_shipment_order_dt = fields.Datetime(string="Shipment Order Date")
    loginext_shipment_order_type_cd = fields.Char(string="Shipment Order Type Code")
    loginext_order_state = fields.Char(string="Order State")
    loginext_distribution_center = fields.Char(string="Distribution Center")
    loginext_return_branch = fields.Char(string="Return Branch")
    loginext_package_weight = fields.Float(string="Package Weight")
    loginext_package_volume = fields.Float(string="Package Volume")
    loginext_preparation_time = fields.Char(string="Preparation Time")
    loginext_payment_type = fields.Char(string="Payment Type")
    loginext_package_value = fields.Float(string="Package Value")
    loginext_number_of_items = fields.Integer(string="Number of Items")
    loginext_partial_delivery_allowed_fl = fields.Boolean(string="Partial Delivery Allowed")
    loginext_return_allowed_fl = fields.Boolean(string="Return Allowed")
    loginext_cancellation_allowed_fl = fields.Boolean(string="Cancellation Allowed")
    loginext_deliver_service_time = fields.Float(string="Deliver Service Time")
    loginext_deliver_start_time_window = fields.Datetime(string="Deliver Start Time Window")
    loginext_deliver_end_time_window = fields.Datetime(string="Deliver End Time Window")
    loginext_delivery_type = fields.Char(string="Delivery Type")
    loginext_deliver_branch = fields.Char(string="Deliver Branch")
    loginext_deliver_account_code = fields.Char(string="Deliver Account Code")
    loginext_deliver_account_name = fields.Char(string="Deliver Account Name")
    loginext_deliver_apartment = fields.Char(string="Deliver Apartment")
    loginext_deliver_street_name = fields.Char(string="Deliver Street Name")
    loginext_deliver_locality = fields.Char(string="Deliver Locality")
    loginext_deliver_city = fields.Char(string="Deliver City")
    loginext_deliver_state = fields.Char(string="Deliver State")
    loginext_deliver_country = fields.Char(string="Deliver Country")
    loginext_deliver_pin_code = fields.Char(string="Deliver Pin Code")
    loginext_deliver_address_timezone = fields.Char(string="Deliver Address Timezone")
    loginext_deliver_notes = fields.Text(string="Deliver Notes")

    odoo_shipment_number = fields.Char(string="Odoo Shipment Number")

    crate_ids = fields.One2many(
        "loginext.staging.crate",
        "staging_id",
        string="Crates",
    )

    line_ids = fields.One2many(
        "loginext.staging.item",
        "staging_id",
        string="Items",
    )


class LoginextStagingCrate(models.Model):
    _name = "loginext.staging.crate"
    _description = "Loginext Staging Crate"

    staging_id = fields.Many2one(
        "loginext.staging.data",
        string="Staging",
        required=True,
        ondelete="cascade",
    )

    loginext_crate_cd = fields.Char(string="Crate Code")
    loginext_crate_name = fields.Char(string="Crate Name")
    loginext_crate_type = fields.Char(string="Crate Type")
    loginext_crate_weight = fields.Float(string="Crate Weight")

    item_ids = fields.One2many(
        "loginext.staging.item",
        "crate_id",
        string="Items",
    )


class LoginextStagingItem(models.Model):
    _name = "loginext.staging.item"
    _description = "Loginext Staging Item"

    crate_id = fields.Many2one(
        "loginext.staging.crate",
        string="Crate",
        required=True,
        ondelete="cascade",
    )

    staging_id = fields.Many2one(
        "loginext.staging.data",
        related="crate_id.staging_id",
        store=True,
        readonly=True,
    )

    loginext_item_cd = fields.Char(string="Item Code")
    loginext_item_name = fields.Char(string="Item Name")
    loginext_item_price = fields.Float(string="Item Price", default='0')
    loginext_item_quantity = fields.Float(string="Item Quantity")
    loginext_item_type = fields.Char(string="Item Type")
    loginext_item_weight = fields.Float(string="Item Weight")
