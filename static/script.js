let WIDTH = 1627
let HEIGHT = 513
let svg = d3.select("#spectrogram")
    .append('svg')
    .attr('width', WIDTH)
    .attr('height', HEIGHT)

let canv = d3.select('#spectrogram')
    .append('canvas')
    .style('position', 'absolute')
    .style('width', `${WIDTH}px`)
    .style('height', `${HEIGHT}px`)
    .attr('width', WIDTH)
    .attr('height', HEIGHT)
    .node()
let ctx = canv.getContext('2d')
let imageData = ctx.getImageData(0, 0, WIDTH, HEIGHT)

let imageBuffer = new ArrayBuffer(imageData.data.length)
let uint8view = new Uint8ClampedArray(imageBuffer)
let uint32view = new Uint32Array(imageBuffer)
    
// List of paths for requesting different data
let RECENT_UPDATE_TS = '/data/spectrogram-update-ts'
let SPECTROGRAM_DATA = '/data/spectrogram-raw'
let SPECTROGRAM_META = '/data/spectrogram-meta'

var lastTimestamp = -1
var specBuffer = null
var timeScale = null
var freqScale = null
var specHeight = 0
var specWidth = 0
var rhsTime = 0  // The time value at the right-hand side of the graph

var logScale = d3.scaleLinear()
    .domain([5e-11, 2e-9])
var colorScale = d3.scaleSequential( (d) => d3.interpolateInferno(logScale(d)) )
logScale.clamp(true)

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
            uint32view[y * specWidth + x] = 
                (255 << 24) | // Alpha channel
                (color.b << 16) |
                (color.g << 8) |
                (color.r)
        }
    }
    imageData.data.set(uint8view)
    ctx.putImageData(imageData, 0, 0)
}

setInterval(attemptUpdateSpec, 0.2)