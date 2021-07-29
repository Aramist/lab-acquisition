let SPEC_MAX_WIDTH = 1627
let SPEC_MAX_HEIGHT = 513

let CAMERA_FEED_WIDTH = 640
let CAMERA_FEED_HEIGHT = 512

// Add clock and timer,
// Possible triggers for emitting sounds through speakers
// Selector to control camera
// 

/*
let svg = d3.select("#spectrogram")
    .append('svg')
    .attr('width', SPEC_MAX_WIDTH)
    .attr('height', SPEC_MAX_HEIGHT)
*/

let specCanvas = d3.select('#spectrogram')
    .append('canvas')
    .style('position', 'relative')
    .style('width', `${SPEC_MAX_WIDTH}px`)
    .style('height', `${SPEC_MAX_HEIGHT}px`)
    .attr('width', SPEC_MAX_WIDTH)
    .attr('height', SPEC_MAX_HEIGHT)
    .node()
let specCtx = specCanvas.getContext('2d')
let specImageData = specCtx.getImageData(0, 0, SPEC_MAX_WIDTH, SPEC_MAX_HEIGHT)
let specImageBuffer = new ArrayBuffer(specImageData.data.length)
let specUint8View = new Uint8ClampedArray(specImageBuffer)
let specUint32View = new Uint32Array(specImageBuffer)


let camCanvas = d3.select('#camera_feed')
    .append('canvas')
    .style('position', 'relative')
    .style('width', `${CAMERA_FEED_WIDTH}px`)
    .style('height', `${CAMERA_FEED_HEIGHT}px`)
    .attr('width', CAMERA_FEED_WIDTH)
    .attr('height', CAMERA_FEED_HEIGHT)
    .node()
let camCtx = camCanvas.getContext('2d')
let camImageData = camCtx.getImageData(0, 0, CAMERA_FEED_WIDTH, CAMERA_FEED_HEIGHT)
let camImageBuffer = new ArrayBuffer(camImageData.data.length)
let camUint8View = new Uint8ClampedArray(camImageBuffer)
let camUint32View = new Uint32Array(camImageBuffer)

    
// List of paths for requesting different data
let RECENT_UPDATE_TS = '/data/spectrogram-update-ts'
let SPECTROGRAM_DATA = '/data/spectrogram-raw'
let SPECTROGRAM_META = '/data/spectrogram-meta'

let VIDEO_DATA = '/data/recent-frame'
let VIDEO_META = '/data/video-meta'

var lastTimestamp = -1
var specBuffer = null
var timeScale = null
var freqScale = null
var specHeight = 0
var specWidth = 0
var rhsTime = 0  // The time value at the right-hand side of the graph

var numCameraChannels = 0
var cameraIntervalId = -1
var cameraBuffer = null

var wrapperScale = d3.scaleLinear()
    .domain([5e-11, 2e-9])
var colorScale = d3.scaleSequential( (d) => d3.interpolateInferno(wrapperScale(d)) )
wrapperScale.clamp(true)

let attemptUpdateSpec = function() {
    d3.json(RECENT_UPDATE_TS).then((data) => {
        if( data.valid ){
            if( lastTimestamp !== data.timestamp ){
                getSpecData();
                lastTimestamp = data.timestamp
            }
        }
    })
}

let getSpecData = function() {
    d3.buffer(SPECTROGRAM_DATA).then((data) => {
        specBuffer = data
        updateDisplay();
    })

    d3.json(SPECTROGRAM_META).then((data) => {
        specHeight = data.dim_freq
        specWidth = data.dim_time
        timeScale = d3.scaleLinear()
            .domain([0, 10])
            .range([0, specWidth])
        let minfreq = data.min_frequency
        let maxfreq = data.max_frequency
        freqScale = d3.scaleLinear()
            .domain([minfreq, maxfreq])
            .range([specHeight, 0])
        rhsTime += data.len_seconds
    })
}

let updateDisplay = function() {
    if (specBuffer.byteLength < 10) {
        return
    }

    array = new Float32Array(specBuffer)
    for(let y = 0; y < specHeight; ++y) {
        for(let x = 0; x < specWidth; ++x) {
            let color = d3.color(colorScale(array[(specHeight - y - 1) * specWidth + x]))
            if (color === undefined || color === null)
                color = {r:0, b:0, g:0}
            specUint32View[y * specWidth + x] = 
                (255 << 24) | // Alpha channel
                (color.b << 16) |
                (color.g << 8) |
                (color.r)
        }
    }
    specImageData.data.set(specUint8View)
    specCtx.putImageData(specImageData, 0, 0)
}

let getCameraParams = function() {
    d3.json(VIDEO_META).then((data) => {
        if(!data.valid) {
            setTimeout(getCameraParams, 1000)
        } else {
            numCameraChannels = data.channels
            setInterval(fetchFrame, 1000/15)
        }
    })
}

let updateImage = function() {
    if (cameraBuffer === undefined || cameraBuffer === null || cameraBuffer.byteLength < 10)
        return

    if (numCameraChannels > 1)
        return

    array = new Uint8ClampedArray(cameraBuffer)
    for(let y = 0; y < CAMERA_FEED_HEIGHT; ++y) {
        for(let x = 0; x < CAMERA_FEED_WIDTH; ++x) {
            pixel = array[y * CAMERA_FEED_WIDTH + x]
            camUint32View[y * CAMERA_FEED_WIDTH + x] = 
                (255 << 24) | // Alpha channel
                (pixel << 16) |
                (pixel << 8) |
                (pixel)
        }
    }

    camImageData.data.set(camUint8View)
    camCtx.putImageData(camImageData, 0, 0)
}

let fetchFrame = function() {
    d3.buffer(VIDEO_DATA).then((data) => {
        cameraBuffer = data
        updateImage()
    })
}

setInterval(attemptUpdateSpec, 200)
setTimeout(getCameraParams, 1000)