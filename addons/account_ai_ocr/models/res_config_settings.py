from odoo import fields, models, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    account_ai_ocr_enabled = fields.Boolean(
        string="AI OCR Invoice Recognition",
        config_parameter='account_ai_ocr.enabled',
    )
    account_ai_ocr_ollama_url = fields.Char(
        string="LLM Server URL",
        config_parameter='account_ai_ocr.ollama_url',
        default='http://192.168.98.72:1234',
    )
    account_ai_ocr_ollama_model = fields.Char(
        string="Vision Model",
        config_parameter='account_ai_ocr.ollama_model',
        default='qwen/qwen3-vl-8b',
    )
    account_ai_ocr_timeout = fields.Integer(
        string="OCR Request Timeout (seconds)",
        config_parameter='account_ai_ocr.timeout',
        default=120,
    )

    def action_test_ollama_connection(self):
        """Test the Ollama connection and model availability."""
        self.ensure_one()
        result = self.env['account.ai.ocr.service']._test_connection()
        if result['success']:
            raise UserError(result['message'])
        else:
            raise UserError(result['message'])
