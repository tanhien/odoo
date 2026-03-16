# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_vn_bank_import_fee_account_code = fields.Char(
        string='Bank Fee Account Code',
        config_parameter='l10n_vn_bank_statement_import.fee_account_code',
        default='6427',
        help='Account code for automatic bank fee posting (e.g. 6427).',
    )
    l10n_vn_bank_import_match_tolerance = fields.Float(
        string='Match Tolerance (VND)',
        config_parameter='l10n_vn_bank_statement_import.match_tolerance',
        default=2000.0,
        help='Maximum amount difference when matching statement lines with invoices.',
    )
