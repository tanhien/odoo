{
    'name': 'AI OCR Invoice Recognition',
    'version': '1.0',
    'summary': 'AI-powered OCR invoice recognition using Ollama local LLM',
    'description': """
Uses a local Ollama LLM with vision capabilities (e.g. llava) to extract
invoice data from uploaded PDF and image files (JPG, PNG).
Extracted data includes vendor name, date, invoice number, line items,
totals, and tax information.
    """,
    'category': 'Accounting/Accounting',
    'depends': ['account'],
    'external_dependencies': {
        'python': ['fitz'],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/account_bank_statement_import_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'account_ai_ocr/static/src/views/file_upload_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
