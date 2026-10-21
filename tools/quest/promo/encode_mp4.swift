// Encode a list of PNG frames into an H.264 MP4 with macOS's own AVFoundation (no ffmpeg).
//   swift encode_mp4.swift <manifest.txt> <out.mp4> <fps>
// The manifest has one line per frame: "<png path>\t<how many video frames to hold it>".
import AVFoundation
import CoreGraphics
import Foundation
import ImageIO

let args = CommandLine.arguments
guard args.count == 4, let fps = Int32(args[3]) else {
    FileHandle.standardError.write("usage: swift encode_mp4.swift <manifest.txt> <out.mp4> <fps>\n".data(using: .utf8)!)
    exit(2)
}
let entries: [(String, Int)] = try String(contentsOfFile: args[1], encoding: .utf8)
    .split(separator: "\n").map { line in
        let parts = line.split(separator: "\t")
        return (String(parts[0]), Int(parts[1])!)
    }

func load(_ path: String) -> CGImage {
    let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil)!
    return CGImageSourceCreateImageAtIndex(src, 0, nil)!
}

let first = load(entries[0].0)
let width = first.width, height = first.height
let outURL = URL(fileURLWithPath: args[2])
try? FileManager.default.removeItem(at: outURL)

let writer = try AVAssetWriter(outputURL: outURL, fileType: .mp4)
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 16_000_000,          // pixel art needs a high bitrate to stay crisp
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        AVVideoMaxKeyFrameIntervalKey: Int(fps) * 2,
    ],
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
])
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

func buffer(for image: CGImage) -> CVPixelBuffer {
    var pb: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pb)
    let buf = pb!
    CVPixelBufferLockBaseAddress(buf, [])
    let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: width, height: height, bitsPerComponent: 8,
                        bytesPerRow: CVPixelBufferGetBytesPerRow(buf), space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
    ctx.interpolationQuality = .none
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    CVPixelBufferUnlockBaseAddress(buf, [])
    return buf
}

var frameIndex: Int64 = 0
for (path, hold) in entries {
    let pb = buffer(for: load(path))
    for _ in 0..<hold {
        while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.005) }
        adaptor.append(pb, withPresentationTime: CMTime(value: frameIndex, timescale: fps))
        frameIndex += 1
    }
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
if writer.status != .completed {
    FileHandle.standardError.write("encode failed: \(String(describing: writer.error))\n".data(using: .utf8)!)
    exit(1)
}
print("wrote \(outURL.path): \(frameIndex) frames at \(fps) fps, \(width)x\(height)")
