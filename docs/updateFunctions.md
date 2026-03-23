# Module `account_ai_ocr` - AI OCR Invoice Recognition with Ollama

## Context

Khi upload hóa đơn (PDF hoặc ảnh) vào Odoo qua nút "Tải lên" trên danh sách hóa đơn, hiện tại Odoo chỉ tạo một invoice trống với file đính kèm. Odoo Enterprise có module `account_invoice_extract` sử dụng AI cloud, nhưng Community edition không có.

**Mục tiêu:** Tạo module mới `account_ai_ocr` sử dụng Ollama local LLM (với vision model như `llava`) để tự động nhận diện và trích xuất dữ liệu từ hóa đơn upload (PDF + ảnh), rồi điền vào invoice.

---

## Module Structure

```
addons/account_ai_ocr/
    __init__.py
    __manifest__.py
    models/
        __init__.py
        account_move.py           # Override _get_edi_decoder + populate invoice
        res_config_settings.py    # Ollama settings
        ai_ocr_service.py        # Ollama API client (AbstractModel)
    views/
        res_config_settings_views.xml
    security/
        ir.model.access.csv
    static/
        src/
            views/
                upload_file_from_data_hook.js  # Extend supportedFileTypes for images
```

---

## Implementation Steps

### Step 1: Module Skeleton

- `__manifest__.py`: depends `['account']`, external_dependencies `{'python': ['fitz']}`
- `__init__.py` files
- `security/ir.model.access.csv` (minimal, AbstractModel không cần table)

**File: `__manifest__.py`**
```python
{
    'name': 'AI OCR Invoice Recognition',
    'version': '1.0',
    'summary': 'AI-powered OCR invoice recognition using Ollama local LLM',
    'category': 'Accounting/Accounting',
    'depends': ['account'],
    'external_dependencies': {
        'python': ['fitz'],  # PyMuPDF
    },
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            ('replace', 'account/static/src/views/upload_file_from_data_hook.js',
             'account_ai_ocr/static/src/views/upload_file_from_data_hook.js'),
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
```

---

### Step 2: `models/ai_ocr_service.py` - Ollama API Client

**Model**: `account.ai.ocr.service` (AbstractModel - không tạo table DB)

#### Methods

| Method | Description |
|--------|-------------|
| `_get_ollama_url()` | Đọc URL từ `ir.config_parameter` (default: `http://localhost:11434`) |
| `_get_ollama_model()` | Đọc model name (default: `llava`) |
| `_get_timeout()` | Đọc timeout setting (default: 120s) |
| `_is_enabled()` | Kiểm tra toggle bật/tắt |
| `_convert_pdf_to_images(pdf_bytes)` | Dùng PyMuPDF (fitz) convert PDF → list PNG bytes, DPI 200, max 3 trang |
| `_extract_invoice_data(image_bytes_list)` | Encode base64, gọi Ollama, parse JSON response |
| `_call_ollama(prompt, images_b64)` | POST `{url}/api/chat` với model, messages (có images), stream=false, format=json |
| `_test_connection()` | Test kết nối Ollama và kiểm tra model khả dụng qua `/api/tags` |

#### Ollama API Request Format
```json
{
  "model": "llava",
  "messages": [{"role": "user", "content": "prompt...", "images": ["base64..."]}],
  "stream": false,
  "format": "json"
}
```

#### Extraction Prompt

Prompt yêu cầu LLM trả về JSON structured với các field:

```json
{
    "vendor_name": "Company name of the vendor/supplier",
    "vendor_vat": "VAT/Tax ID number of the vendor if visible",
    "invoice_number": "The invoice number/reference",
    "invoice_date": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD or null",
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
```

**Rules trong prompt:**
- Tất cả monetary amounts phải là numbers (không phải strings)
- Quantities phải là numbers
- Dates phải ở format YYYY-MM-DD
- Nếu có nhiều tax rates, include `tax_percent` trên mỗi line
- Với multi-page invoices, combine data từ tất cả pages
- Nếu document không phải invoice, set tất cả fields thành null

---

### Step 3: `models/account_move.py` - Decoder Integration

**Inherit**: `account.move`

Theo đúng pattern của `account_edi_ubl_cii` (priority 20) và `l10n_it_edi`:

#### 3.1 `_get_import_file_type(file_data)`

Nhận diện image files:
```python
if mimetype in ('image/jpeg', 'image/png', 'image/jpg'):
    return 'image'
return super()._get_import_file_type(file_data)
```

#### 3.2 `_get_edi_decoder(file_data, new)`

Đăng ký AI OCR decoder:
- Kiểm tra `_is_enabled()`
- Nếu file type là `pdf` hoặc `image`, return `{'decoder': _decode_with_ai_ocr, 'priority': 5}`
- **Priority 5** (thấp hơn EDI decoders priority 20) → AI OCR chỉ là fallback
- Nếu `super()` trả về decoder có priority > 5, dùng decoder đó thay vì AI OCR
- Gọi `super()` cho các file type khác

#### 3.3 `_decode_with_ai_ocr(invoice, file_data, new)`

Decoder function chính:
1. Kiểm tra `invoice.invoice_line_ids` (skip nếu đã có lines)
2. **PDF** → convert to images via `_convert_pdf_to_images()`
3. **Image** → dùng trực tiếp `file_data['raw']`
4. Gọi `_extract_invoice_data()` → nhận dict
5. Gọi `_populate_invoice_from_ocr()` để điền dữ liệu
6. Return `None` (thành công) hoặc string (lý do thất bại)

#### 3.4 `_populate_invoice_from_ocr(invoice, data, new)`

Điền invoice fields:
- Dùng `invoice._get_edi_creation()` context manager (defer dynamic line computation)
- **Match partner**: `res.partner._retrieve_partner(name=vendor_name, vat=vendor_vat)`
  - Search by VAT first (most reliable), then by name
- Set `currency_id`, `invoice_date`, `invoice_date_due`
- Set `ref` (vendor bill) hoặc `name` (customer invoice) cho invoice number
- Set `payment_reference`, `narration` (notes)
- Tạo invoice lines với `Command.create()`:
  - `name` (description)
  - `quantity`
  - `price_unit`
  - `tax_ids` (match `account.tax` theo amount + type_tax_use)
- Post message vào chatter với kết quả import + warnings

#### 3.5 `_should_attach_to_record(attachment)`

Chấp nhận image attachments (để hiển thị trong chatter):
```python
if mimetype in ('image/jpeg', 'image/png'):
    return True
return super()._should_attach_to_record(attachment)
```

#### 3.6 `_match_ocr_partner(company, vendor_name, vendor_vat)`

Sử dụng `res.partner._retrieve_partner()` có sẵn trong Odoo:
- Tìm theo VAT trước (chính xác nhất)
- Sau đó tìm theo domain
- Sau đó tìm theo phone/email
- Cuối cùng tìm theo name (ilike)

#### 3.7 `_prepare_ocr_invoice_line(invoice, line_data)`

Convert OCR line dict → invoice line vals:
- `display_type`: `'product'`
- `name`: description
- `quantity`: float
- `price_unit`: float
- `tax_ids`: tìm `account.tax` theo `amount` = tax_percent, `amount_type` = 'percent', `type_tax_use` = sale/purchase

---

### Step 4: `models/res_config_settings.py` - Settings

Fields với `config_parameter`:

| Field | Type | Default | Config Parameter |
|-------|------|---------|-----------------|
| `account_ai_ocr_enabled` | Boolean | False | `account_ai_ocr.enabled` |
| `account_ai_ocr_ollama_url` | Char | `http://localhost:11434` | `account_ai_ocr.ollama_url` |
| `account_ai_ocr_ollama_model` | Char | `llava` | `account_ai_ocr.ollama_model` |
| `account_ai_ocr_timeout` | Integer | 120 | `account_ai_ocr.timeout` |

**Button**: `action_test_ollama_connection()` - test kết nối, gọi `/api/tags` endpoint

---

### Step 5: `views/res_config_settings_views.xml`

Inherit `account.res_config_settings_view_form`, thêm block "AI Invoice Recognition (Local LLM)" sau block `account_digitalization`:

- Toggle bật/tắt AI OCR
- URL Ollama server (ẩn khi tắt)
- Vision Model name (ẩn khi tắt)
- Timeout (ẩn khi tắt)
- Nút "Test Connection" với icon `fa-plug`

---

### Step 6: Frontend - Extend Image Support for Paste

**File**: `static/src/views/upload_file_from_data_hook.js`

Sử dụng asset `replace` directive trong `__manifest__.py` để thay thế file gốc từ module `account`.

Thay đổi duy nhất: thêm `"image/jpeg"` và `"image/png"` vào `supportedFileTypes`:

```javascript
// Before (account module):
const supportedFileTypes = ["text/xml", "application/pdf"];

// After (account_ai_ocr module):
const supportedFileTypes = ["text/xml", "application/pdf", "image/jpeg", "image/png"];
```

**Note:** File picker (click "Upload") đã accept tất cả file types mặc định. Chỉ cần sửa paste handler.

---

## Key Reference Files

| File | Purpose |
|------|---------|
| `addons/account/models/account_document_import_mixin.py` | Decoder framework (`_get_edi_decoder`, `_extend_with_attachments`) |
| `addons/account/models/account_move.py:4824` | `_get_edi_creation()` context manager |
| `addons/account/models/account_move.py:4850` | `_reason_cannot_decode_has_invoice_lines()` |
| `addons/account_edi_ubl_cii/models/account_move.py:298` | Reference `_get_edi_decoder` override (priority 20) |
| `addons/account/models/partner.py:959` | `_retrieve_partner()` for vendor matching |
| `addons/account/static/src/views/upload_file_from_data_hook.js` | Paste file type validation |
| `addons/account/models/ir_attachment.py:84` | `_post_add_create` hook |

---

## Upload Flow (How It Works)

```
User clicks "Tải lên" / paste file
         |
         v
Frontend: DocumentFileUploader.onFileUploaded()
    → creates ir.attachment record
         |
         v
Frontend: DocumentFileUploader.onUploadComplete()
    → calls account.journal.create_document_from_attachment(attachment_ids)
         |
         v
Backend: account.journal._create_document_from_attachment()
    → calls account.move._create_records_from_attachments(attachments)
         |
         v
Mixin: _create_records_from_attachments()
    → _to_files_data(attachments)           # Convert to file_data dicts
    → _unwrap_attachments(files_data)       # Extract embedded PDF files
    → _group_files_data(files_data)         # Group into invoice groups
    → create([{}] * len(groups))            # Create empty invoices
    → _extend_with_attachments(files_data)  # Apply decoders
         |
         v
Mixin: _extend_with_attachments()
    → _get_edi_decoder(file_data, new)      # *** OUR HOOK POINT ***
    → sorts by priority (highest wins)
    → calls decoder function
         |
         v
AI OCR: _decode_with_ai_ocr(invoice, file_data, new)
    → _convert_pdf_to_images() or use raw bytes
    → _extract_invoice_data(images)
         → _call_ollama(prompt, images_b64)  # POST to Ollama /api/chat
         → parse JSON response
    → _populate_invoice_from_ocr(invoice, data, new)
         → match partner (VAT → name)
         → set dates, currency, reference
         → create invoice lines with taxes
         → post chatter message
```

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Ollama không kết nối | Return failure reason string, framework post vào chatter |
| PDF corrupt | `_convert_pdf_to_images` raises, caught by decoder |
| LLM trả về JSON sai | `json.loads` fail, return error message |
| Partner không tìm thấy | Log warning vào chatter, invoice vẫn tạo (không có partner) |
| Tax không match | Skip tax assignment cho line đó, log warning |
| Framework exception | `rollbackable_transaction` tự rollback, post error vào chatter |
| Ollama model not found | `_test_connection()` báo lỗi, hướng dẫn `ollama pull <model>` |

---

## Installation & Usage

### Prerequisites
1. **Python**: `pip install PyMuPDF`
2. **Ollama**: Install from https://ollama.ai
3. Pull vision model: `ollama pull llava`
4. Start Ollama: `ollama serve`

### Install Module
1. Update Apps List in Odoo
2. Search "AI OCR Invoice Recognition"
3. Click Install

### Configure
1. Go to: **Accounting → Settings**
2. Find section: **AI Invoice Recognition (Local LLM)**
3. Enable toggle
4. Set Ollama URL (default: `http://localhost:11434`)
5. Set Vision Model (default: `llava`)
6. Set Timeout (default: 120 seconds)
7. Click **Test Connection** to verify
8. **Save**

### Use
1. Go to **Customer Invoices** or **Vendor Bills**
2. Click **"Tải lên"** (Upload) button
3. Select PDF or image file (JPG, PNG)
4. Wait for AI processing (may take 10-60s depending on model)
5. Invoice is auto-populated with extracted data
6. Check chatter for import log and any warnings
7. Review and adjust data as needed

---

## Verification Checklist

- [ ] Module installs without errors
- [ ] Settings page shows AI OCR section
- [ ] Test Connection button works (success/failure messages)
- [ ] Upload PDF invoice → invoice populated with data
- [ ] Upload image (JPG/PNG) invoice → invoice populated with data
- [ ] Partner matching works (by VAT and by name)
- [ ] Invoice lines created with correct quantities and prices
- [ ] Tax matching works for standard tax rates
- [ ] Chatter shows import log message
- [ ] Chatter shows warnings for unmatched partners/taxes
- [ ] Paste image file works on invoice list view
- [ ] AI OCR disabled → upload works normally (no AI processing)
- [ ] EDI decoder wins over AI OCR when both available (priority check)
