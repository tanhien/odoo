import base64
import json
import logging
import urllib.request
import urllib.error

from odoo import api, models, _

_logger = logging.getLogger(__name__)

INVOICE_EXTRACTION_PROMPT = """You are an invoice data extraction system. Analyze this invoice image and extract all data into a structured JSON format.

Extract the following information. If a field cannot be found, use null.

Return ONLY valid JSON with this exact structure:
{
    "vendor_name": "Company name of the vendor/supplier",
    "vendor_vat": "VAT/Tax ID number of the vendor if visible",
    "invoice_number": "The invoice number/reference",
    "invoice_date": "Invoice date in YYYY-MM-DD format",
    "due_date": "Payment due date in YYYY-MM-DD format or null",
    "currency": "3-letter ISO currency code (e.g., VND, EUR, USD)",
    "payment_reference": "Payment reference if visible",
    "lines": [
        {
            "description": "Product or service description",
            "quantity": 1.0,
            "unit_price": 0.00,
            "tax_percent": null,
            "line_total": 0.00
        }
    ],
    "subtotal": 0.00,
    "tax_amount": 0.00,
    "total_amount": 0.00,
    "notes": "Any additional notes or payment terms"
}

Rules:
- All monetary amounts must be plain integer or decimal numbers WITHOUT any thousand separators
- CRITICAL for Vietnamese invoices (VND): dots and commas in prices are THOUSAND SEPARATORS, not decimal points. VND has no decimal places.
  Examples: "31.818" on invoice means 31818, "1.500.000" means 1500000, "250,000" means 250000
- For other currencies (EUR, USD): dots are decimal separators, commas are thousand separators.
  Examples: "1,500.00" means 1500.00, "31.82" means 31.82
- If currency is VND or the invoice is in Vietnamese, always return whole numbers for amounts (no decimals)
- Quantities must be numbers
- Dates must be in YYYY-MM-DD format
- If there are multiple tax rates, include tax_percent on each line
- For multi-page invoices, combine data from all pages
- If the document is not an invoice, set all fields to null
- Return ONLY the JSON, no explanation text"""


class AccountAiOcrService(models.AbstractModel):
    _name = 'account.ai.ocr.service'
    _description = 'AI OCR Service'

    def _get_llm_url(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'account_ai_ocr.ollama_url',
            default='http://192.168.98.72:1234',
        )

    def _get_llm_model(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'account_ai_ocr.ollama_model',
            default='qwen/qwen3-vl-8b',
        )

    def _get_timeout(self):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(
                'account_ai_ocr.timeout',
                default='120',
            ))
        except (ValueError, TypeError):
            return 120

    def _is_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'account_ai_ocr.enabled',
            default='False',
        ) == 'True'

    def _convert_pdf_to_images(self, pdf_bytes):
        """Convert PDF binary content to a list of PNG image bytes.

        Uses PyMuPDF (fitz) for cross-platform PDF rendering.
        Returns only the first 3 pages to limit processing time.
        """
        import fitz  # PyMuPDF

        images = []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for page_num in range(min(doc.page_count, 3)):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=200)
                images.append(pix.tobytes("png"))
        finally:
            doc.close()
        return images

    def _extract_invoice_data(self, image_bytes_list):
        """Send images to LLM vision model and parse the JSON response.

        :param image_bytes_list: list of PNG/JPG image bytes
        :returns: dict with extracted invoice data, or None on failure
        """
        images_b64 = [
            base64.b64encode(img).decode('utf-8')
            for img in image_bytes_list
        ]

        try:
            result = self._call_llm(INVOICE_EXTRACTION_PROMPT, images_b64)
        except Exception as e:
            _logger.warning("LLM API call failed: %s", e)
            raise

        if not result:
            return None

        # Validate minimum required data
        if not result.get('lines') and not result.get('total_amount'):
            _logger.info("AI OCR returned no meaningful data")
            return None

        # Post-process amounts for VND (no decimal currency)
        result = self._postprocess_amounts(result)

        return result

    def _postprocess_amounts(self, data):
        """Fix amounts for currencies with no decimal places (VND).

        Vietnamese invoices use dots/commas as thousand separators.
        If LLM returns 31.818 for VND, it should be 31818.
        Heuristic: if currency is VND and amount has exactly 3 decimal digits,
        treat the dot as a thousand separator.
        """
        currency = (data.get('currency') or '').upper()
        is_vnd = currency == 'VND'

        # Also detect VND if not explicitly set but amounts look like VND format
        if not currency:
            # If total_amount > 1000 and is a whole number, likely VND
            total = data.get('total_amount')
            if isinstance(total, (int, float)) and total > 1000 and total == int(total):
                is_vnd = True
                data['currency'] = 'VND'

        if not is_vnd:
            return data

        # Fix top-level amount fields
        for key in ('subtotal', 'tax_amount', 'total_amount'):
            if data.get(key) is not None:
                data[key] = self._fix_vnd_amount(data[key])

        # Fix line amounts
        for line in (data.get('lines') or []):
            for key in ('unit_price', 'line_total'):
                if line.get(key) is not None:
                    line[key] = self._fix_vnd_amount(line[key])

        return data

    def _fix_vnd_amount(self, value):
        """Fix a single VND amount value.

        VND has no decimal places. If the value looks like it has
        thousand separators misinterpreted as decimals, fix it.

        Examples:
            31.818    -> 31818   (dot was thousand separator)
            1.500.000 -> 1500000 (string with dots)
            1500000   -> 1500000 (already correct)
            31818     -> 31818   (already correct)
        """
        if isinstance(value, str):
            # Remove dots and commas that are thousand separators
            cleaned = value.replace('.', '').replace(',', '')
            try:
                return int(cleaned)
            except ValueError:
                return value

        if isinstance(value, float):
            # Check if this looks like a misinterpreted thousand separator
            # e.g., 31.818 should be 31818, 1500.0 should be 1500
            str_val = str(value)
            if '.' in str_val:
                decimal_part = str_val.split('.')[1]
                # If exactly 3 decimal digits -> likely thousand separator (31.818 -> 31818)
                if len(decimal_part) == 3:
                    return int(value * 1000)
                # If 6 decimal digits -> two thousand groups (1.500000 from 1.500.000)
                if len(decimal_part) == 6:
                    return int(value * 1000000)
            # Otherwise just round to int for VND
            return int(round(value))

        if isinstance(value, int):
            return value

        return value

    def _call_llm(self, prompt, images_b64):
        """Call LLM API with OpenAI-compatible vision format.

        Tries multiple endpoints to find the correct one.
        Uses multimodal content format for vision models.

        :param prompt: The text prompt to send
        :param images_b64: list of base64-encoded image strings
        :returns: parsed JSON dict from the LLM response
        :raises: Exception on connection or parsing errors
        """
        url = self._get_llm_url().rstrip('/')
        model = self._get_llm_model()
        timeout = self._get_timeout()

        # Build multimodal content: images first, then text
        content = []
        for img_b64 in images_b64:
            content.append({
                'type': 'image_url',
                'image_url': {
                    'url': f'data:image/png;base64,{img_b64}',
                },
            })
        content.append({
            'type': 'text',
            'text': prompt,
        })

        payload = {
            'model': model,
            'messages': [{
                'role': 'user',
                'content': content,
            }],
            'stream': False,
            'temperature': 0.1,
            'max_tokens': 4096,
        }

        # Try multiple chat endpoints
        endpoints = [
            '/v1/chat/completions',
            '/api/v1/chat/completions',
            '/api/v1/chat',
            '/api/chat',
        ]

        last_error = None
        for endpoint in endpoints:
            full_url = f'{url}{endpoint}'
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                full_url,
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )

            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    response_data = json.loads(response.read().decode('utf-8'))
                _logger.info("LLM call succeeded on endpoint: %s", endpoint)
                break
            except urllib.error.HTTPError as e:
                # Read the error response body for debugging
                error_body = ''
                try:
                    error_body = e.read().decode('utf-8')[:500]
                except Exception:
                    pass
                _logger.info("LLM endpoint %s returned HTTP %s: %s",
                             endpoint, e.code, error_body)
                last_error = e
                continue
            except urllib.error.URLError as e:
                _logger.info("LLM endpoint %s failed: %s", endpoint, e)
                last_error = e
                continue
        else:
            # All endpoints failed
            raise ConnectionError(
                _("Cannot connect to LLM server at %(url)s. "
                  "Tried endpoints: %(endpoints)s. Last error: %(error)s",
                  url=url,
                  endpoints=', '.join(endpoints),
                  error=str(last_error))
            )

        _logger.info("LLM raw response keys: %s", list(response_data.keys()))

        # Support both OpenAI format and Ollama format
        # OpenAI: response_data['choices'][0]['message']['content']
        # Ollama: response_data['message']['content']
        content_str = ''
        if 'choices' in response_data:
            choices = response_data.get('choices', [])
            if choices:
                content_str = choices[0].get('message', {}).get('content', '')
        elif 'message' in response_data:
            content_str = response_data.get('message', {}).get('content', '')

        if not content_str:
            _logger.warning("LLM returned empty content. Full response: %s",
                            json.dumps(response_data, ensure_ascii=False)[:1000])
            return None

        try:
            return json.loads(content_str)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block ```json ... ```
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content_str)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            _logger.warning("Failed to parse LLM response as JSON: %s", content_str[:500])
            return None

    def _test_connection(self):
        """Test LLM server connectivity.

        :returns: dict with 'success' bool and 'message' string
        """
        url = self._get_llm_url().rstrip('/')
        model = self._get_llm_model()

        # Try multiple model listing endpoints
        for endpoint in ['/api/v1/models', '/v1/models', '/api/tags']:
            try:
                req = urllib.request.Request(f'{url}{endpoint}', method='GET')
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode('utf-8'))
            except Exception:
                continue

            _logger.info("LLM model list from %s%s: %s",
                         url, endpoint, json.dumps(data, ensure_ascii=False)[:2000])

            # Extract model names from various API formats
            available_models = []
            model_objects = data.get('data', []) or data.get('models', []) or []
            for m in model_objects:
                if isinstance(m, dict):
                    # Try common keys: id, name, model
                    name = m.get('id') or m.get('name') or m.get('model') or ''
                    if name:
                        available_models.append(str(name))
                elif isinstance(m, str):
                    available_models.append(m)

            # Flexible model matching: check if configured model is in any available model name
            model_found = (
                not available_models  # if no models listed, skip check
                or model in available_models
                or any(model in m or m in model for m in available_models)
            )

            if not model_found:
                return {
                    'success': False,
                    'message': _("Connected to LLM server, but model '%(model)s' not found. "
                                 "Available models: %(available)s",
                                 model=model,
                                 available=', '.join(available_models[:10]) or 'none'),
                }

            return {
                'success': True,
                'message': _("Successfully connected to LLM server at %(url)s. "
                             "Model '%(model)s' is available. "
                             "Endpoint: %(endpoint)s",
                             url=url, model=model, endpoint=endpoint),
            }

        # All endpoints failed - try a simple connectivity check
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=10):
                return {
                    'success': True,
                    'message': _("Connected to LLM server at %(url)s. "
                                 "Could not list models, but server is reachable. "
                                 "Model '%(model)s' will be used.",
                                 url=url, model=model),
                }
        except Exception as e:
            return {
                'success': False,
                'message': _("Cannot connect to LLM server at %(url)s: %(error)s",
                             url=url, error=str(e)),
            }
