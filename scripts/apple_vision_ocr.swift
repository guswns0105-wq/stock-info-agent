import Foundation
import Vision
import AppKit

if CommandLine.arguments.count < 2 {
    fputs("usage: apple_vision_ocr.swift IMAGE\n", stderr)
    exit(2)
}
let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: imageURL), let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("failed to load image\n", stderr)
    exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["ko-KR", "en-US"]
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
    var rows: [[String: Any]] = []
    for obs in request.results ?? [] {
        guard let cand = obs.topCandidates(1).first else { continue }
        rows.append([
            "text": cand.string,
            "confidence": cand.confidence,
            "bbox": [obs.boundingBox.origin.x, obs.boundingBox.origin.y, obs.boundingBox.size.width, obs.boundingBox.size.height]
        ])
    }
    let data = try JSONSerialization.data(withJSONObject: rows, options: [])
    FileHandle.standardOutput.write(data)
} catch {
    fputs("ocr error: \(error)\n", stderr)
    exit(1)
}
