# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_vn_einvoice_llm_url = fields.Char(
        string='LLM API URL',
        config_parameter='l10n_vn_einvoice_import.llm_url',
        default='http://192.168.1.185:1234/v1/chat/completions',
        help='URL of the OpenAI-compatible LLM API endpoint for PDF OCR.',
    )
    l10n_vn_einvoice_llm_model = fields.Char(
        string='LLM Model',
        config_parameter='l10n_vn_einvoice_import.llm_model',
        default='qwen/qwen3-vl-8b',
        help='Vision-language model name for PDF OCR processing.',
    )
    l10n_vn_einvoice_llm_timeout = fields.Integer(
        string='LLM Timeout (seconds)',
        config_parameter='l10n_vn_einvoice_import.llm_timeout',
        default=120,
        help='Timeout in seconds for LLM API requests.',
    )
