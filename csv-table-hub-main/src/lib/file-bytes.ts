// The file's bytes exactly as on disk, base64-encoded (#185; BR-24).
// FileReader.readAsText drops a BOM and replaces invalid bytes, so the text the
// loaders receive can't be hashed or stored as "the original". The API keeps
// these bytes as the preserved original and still loads from the decoded text.

const CHUNK = 0x8000; // keeps String.fromCharCode's argument list well under engine limits

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

export function readFileBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file."));
    reader.onload = () => resolve(bytesToBase64(new Uint8Array(reader.result as ArrayBuffer)));
    reader.readAsArrayBuffer(file);
  });
}
