// remove_background.swift
// Usage: swift remove_background.swift <input.png> <output.png>
// Requires macOS 14+ (Sonoma) for VNGenerateForegroundInstanceMaskRequest

import Foundation
import AppKit
import Vision
import CoreImage
import CoreImage.CIFilterBuiltins

// MARK: - Argument parsing

guard CommandLine.arguments.count == 3 else {
    let name = (CommandLine.arguments.first as NSString?)?.lastPathComponent ?? "remove_background"
    fputs("Usage: \(name) <input.png> <output.png>\n", stderr)
    exit(1)
}

let inputPath = CommandLine.arguments[1]
let outputPath = CommandLine.arguments[2]

// MARK: - Load input image

guard let inputURL = URL(string: "file://" + (inputPath as NSString).standardizingPath),
      FileManager.default.fileExists(atPath: inputURL.path) else {
    fputs("Error: Input file not found at \(inputPath)\n", stderr)
    exit(1)
}

guard let ciImage = CIImage(contentsOf: inputURL) else {
    fputs("Error: Could not load image from \(inputPath)\n", stderr)
    exit(1)
}

// MARK: - Generate foreground mask using Vision

func createMask(from inputImage: CIImage) -> CIImage? {
    let request = VNGenerateForegroundInstanceMaskRequest()
    let handler = VNImageRequestHandler(ciImage: inputImage, options: [:])

    do {
        try handler.perform([request])

        guard let result = request.results?.first else {
            fputs("Error: No mask results returned by Vision\n", stderr)
            return nil
        }

        let maskPixelBuffer = try result.generateScaledMaskForImage(
            forInstances: result.allInstances,
            from: handler
        )
        return CIImage(cvPixelBuffer: maskPixelBuffer)
    } catch {
        fputs("Error generating mask: \(error.localizedDescription)\n", stderr)
        return nil
    }
}

// MARK: - Apply mask to original image

func applyMask(_ mask: CIImage, to image: CIImage) -> CIImage? {
    let filter = CIFilter.blendWithMask()
    filter.inputImage = image
    filter.maskImage = mask
    filter.backgroundImage = CIImage.empty()
    return filter.outputImage
}

// MARK: - Save as PNG with alpha

func savePNG(ciImage: CIImage, to path: String) -> Bool {
    let context = CIContext(options: nil)

    guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else {
        fputs("Error: Failed to render CGImage\n", stderr)
        return false
    }

    let bitmapRep = NSBitmapImageRep(cgImage: cgImage)
    bitmapRep.hasAlpha = true

    guard let pngData = bitmapRep.representation(using: .png, properties: [:]) else {
        fputs("Error: Failed to create PNG data\n", stderr)
        return false
    }

    let outputURL = URL(fileURLWithPath: (path as NSString).standardizingPath)
    do {
        try pngData.write(to: outputURL)
        return true
    } catch {
        fputs("Error writing file: \(error.localizedDescription)\n", stderr)
        return false
    }
}

// MARK: - Main

print("Loading image from: \(inputPath)")

guard let mask = createMask(from: ciImage) else {
    fputs("Failed to create foreground mask.\n", stderr)
    exit(1)
}

print("Foreground mask generated.")

guard let result = applyMask(mask, to: ciImage) else {
    fputs("Failed to apply mask to image.\n", stderr)
    exit(1)
}

print("Mask applied. Saving result...")

if savePNG(ciImage: result, to: outputPath) {
    print("Background removed successfully. Output saved to: \(outputPath)")
} else {
    fputs("Failed to save output image.\n", stderr)
    exit(1)
}
