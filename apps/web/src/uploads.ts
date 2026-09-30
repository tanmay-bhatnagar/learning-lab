export const MAX_PDF_BYTES = 25 * 1024 * 1024;

export function pdfDropBlocked(options: { busy: boolean; topicReady: boolean; hasTopic: boolean }): string | null {
  if (!options.hasTopic) return 'Choose a topic before adding PDFs.';
  if (!options.topicReady) return 'Wait for this topic to finish loading before adding files.';
  if (options.busy) return 'Finish the current action before adding files.';
  return null;
}

// Validate the entire batch before uploading anything, for both browse and drop.
export async function validatePdfs(files: File[]): Promise<void> {
  for (const file of files) {
    if (
      !file.name.toLowerCase().endsWith('.pdf') ||
      (file.type && !['application/pdf', 'application/octet-stream'].includes(file.type))
    ) {
      throw new Error(`“${file.name}” is not a PDF. Choose PDF files to upload.`);
    }
    if (!file.size) throw new Error(`“${file.name}” is empty.`);
    if (file.size > MAX_PDF_BYTES) throw new Error(`“${file.name}” exceeds the 25 MiB PDF limit.`);
    if ((await file.slice(0, 5).text()) !== '%PDF-')
      throw new Error(`“${file.name}” does not have a valid PDF header.`);
  }
}
