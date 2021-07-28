// Hard coding these constants is a bad idea but I have no good way to resize the image
let SPEC_MAX_WIDTH = 1627
let SPEC_MAX_HEIGHT = 513
let CAMERA_FEED_WIDTH = 640
let CAMERA_FEED_HEIGHT = 512

let VIDEO_CACHE_SIZE = 30
let SPEC_CACHE_SIZE = 8

let VIDEO_FRAMERATE = 20

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
let SPECTROGRAM_DATA = '/data/spectrogram/data'
let SPECTROGRAM_META = '/data/spectrogram/meta'

let VIDEO_DATA = '/data/video/data'
let VIDEO_META = '/data/video/meta'

// Spectrogram feed constants
class SpecMeta {
    constructor(){
        this.id = -1
        this.timeScale = null
        this.freqScale = null
        this.height = 0
        this.width = 0
        this.rhsTime = 0  // The time value at the right-hand side of the graph
    }
}

specDataArr = new Array()
specMetaArr = new Array()
var nextDisplaySpec = 0  // Id of the next frame to display

// Video feed constants
var videoMeta = {
    numCameraChannels: 0,
    height: CAMERA_FEED_HEIGHT,
    width: CAMERA_FEED_WIDTH,
}
var frameDataArr = new Array()
var frameIdArr = new Array()
var nextDisplayFrame = 0

var wrapperScale = d3.scaleLinear()
    .domain([5e-11, 2e-9])
wrapperScale.clamp(true)
var colorScale = d3.scaleSequential( (d) => d3.interpolateInferno(wrapperScale(d)) )

var specDisplaying = false
var videoDisplaying = false

let deque_append = function(arr, size, element) {
    if(arr.length >= size) {
        arr = arr.slice(1)
    }
    arr.push(element)
    return arr
}

/* Proceeding: functions for the spectrogram
    Lifecycle: Start by requesting meta, if available, start requesting frames for caching
        - meta should be requested (16Hz) prior to requesting any data hereafter
        - append any new meta to meta deque, if full, begin display calls
        - request data at the end of meta request call, if there is data to request
*/
let attemptUpdateSpec = function() {
    if(specDataArr.length > SPEC_CACHE_SIZE)
        return
    d3.json(SPECTROGRAM_META).then((data) => {
        let specMeta = new SpecMeta();
        specMeta.id = data.id
        specMeta.height = data.dim_freq
        specMeta.width = data.dim_time
        specMeta.timeScale = d3.scaleLinear()
            .domain([0, 10])
            .range([0, specMeta.width])
        let minfreq = data.min_frequency
        let maxfreq = data.max_frequency
        specMeta.freqScale = d3.scaleLinear()
            .domain([minfreq, maxfreq])
            .range([specMeta.height, 0])
        specMeta.rhsTime += data.len_seconds  // TODO: This definitely doesn't actually work

        specMetaArr = deque_append(specMetaArr, SPEC_CACHE_SIZE, specMeta)
        getSpecData(specMeta.id)
    })
    .catch((error) => {})
}

let getSpecData = function(id) {
    d3.buffer(`${SPECTROGRAM_DATA}?id=${id}`).then((data) => {
        specDataArr = deque_append(specDataArr, SPEC_CACHE_SIZE, data)
        if(specDataArr.length >= SPEC_CACHE_SIZE && !specDisplaying) {
            specDisplaying = true
            nextDisplaySpec = specMetaArr[0].id
            setInterval(updateDisplay, 1000/SPEC_CACHE_SIZE);
        }
    })
    .catch((error) => {})
}

let updateDisplay = function() {
    let buffer = specDataArr.shift()
    let meta = specMetaArr.shift()

    // Ensure the right frame is being used:

    let diff = SPEC_MAX_WIDTH - meta.width;
    let array = new Float32Array(buffer)
    for(let y = 0; y < meta.height; ++y) {
        for(let x = 0; x < meta.width; ++x) {
            let color = d3.color(colorScale(array[(meta.height - y - 1) * meta.width + x]))
            if (color === undefined || color === null)
                color = {r:0, b:0, g:0}
            specUint32View[y * SPEC_MAX_WIDTH + x + diff] = 
                (255 << 24) | // Alpha channel
                (color.b << 16) |
                (color.g << 8) |
                (color.r)
        }
    }
    specImageData.data.set(specUint8View)
    specCtx.putImageData(specImageData, 0, 0)
}
// End of spectrogram display functions


let getCameraParams = function() {
    if(frameDataArr.length > VIDEO_CACHE_SIZE)
        return;
    d3.json(VIDEO_META).then((data) => {
        videoMeta.numCameraChannels = data.channels
        videoMeta.height = data.height
        videoMeta.width = data.width
        let id = data.id
        if(VIDEO_FRAMERATE < 30){
            // Will take to long to implement, assume 20
            if(id % 3 == 0)  // Drop every third frame
                return
        }
        frameIdArr = deque_append(frameIdArr, VIDEO_CACHE_SIZE, data.id)
        fetchFrame(id)
    })
    .catch((error) => {
        // setTimeout(getCameraParams, 1000)
    })
}

let fetchFrame = function(id) {
    d3.buffer(`${VIDEO_DATA}?id=${id}`).then((data) => {
        frameDataArr = deque_append(frameDataArr, VIDEO_CACHE_SIZE, data)
        if(frameDataArr.length >= VIDEO_CACHE_SIZE && !videoDisplaying) {
            videoDisplaying = true
            nextDisplayFrame = frameIdArr[0]
            setInterval(updateImage, 1000/VIDEO_FRAMERATE)
        }
    })
    .catch((error) => {})
}

let updateImage = function() {
    let buffer = frameDataArr.shift()
    let id = frameIdArr.shift()

    // Ensure the right frame is being used:

    if (videoMeta.numCameraChannels > 1)
        return

    array = new Uint8ClampedArray(buffer)
    for(let y = 0; y < videoMeta.height; ++y) {
        for(let x = 0; x < videoMeta.width; ++x) {
            pixel = array[y * videoMeta.width + x]
            camUint32View[y * videoMeta.width + x] = 
                (255 << 24) | // Alpha channel
                (pixel << 16) |
                (pixel << 8) |
                (pixel)
        }
    }

    camImageData.data.set(camUint8View)
    camCtx.putImageData(camImageData, 0, 0)
}


d3.select(window)
    .on('load', () => {
        setInterval(attemptUpdateSpec, 1000 / SPEC_CACHE_SIZE / 2)
        setInterval(getCameraParams, 1000 / 30 / 2)
    })
