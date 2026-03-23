/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { FileUploadListRenderer } from "@account/views/file_upload_list/file_upload_list_renderer";

// Supported file types extended with image types for AI OCR
const supportedFileTypes = ["text/xml", "application/pdf", "image/jpeg", "image/png"];

patch(FileUploadListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        // Override the paste handler to also accept image files
        this.uploadFileFromData = (dataTransfer) => {
            function uploadFiles(dataTransfer) {
                const invalidFiles = [...dataTransfer.items].filter(
                    (item) => item.kind !== "file" || !supportedFileTypes.includes(item.type)
                );
                if (invalidFiles.length !== 0) {
                    console.warn("Invalid files to extract details.");
                    return;
                }
                let uploadInput = document.querySelector('.document_file_uploader.o_input_file');
                uploadInput.files = dataTransfer.files;
                uploadInput.dispatchEvent(new Event("change"));
            }
            if (dataTransfer.files.length !== 0) {
                uploadFiles(dataTransfer);
            } else {
                console.warn("Invalid data to extract details.");
            }
        };
    },
});
