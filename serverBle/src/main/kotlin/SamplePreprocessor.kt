// Applica sul PC il denoise wavelet al solo giroscopio, per il riconoscimento dei gesti.
// Esce un pacchetto con: clean = (acc, gyro denoisato, mag) e raw = tutto grezzo.
class SamplePreprocessor(private val denoiseOnPc: Boolean) {
    private val denoiser = WaveletDenoiser(nChannels = 3)

    fun process(p: ImuPacket): ImuPacket {
        if (!denoiseOnPc) return p
        // Se l'orologio non invia il raw, il blocco "clean" contiene già il grezzo
        val rawData = p.raw ?: p.clean
        val gyro = floatArrayOf(rawData[3], rawData[4], rawData[5])
        val den = denoiser.update(gyro) ?: gyro   // finché non è pieno: grezzo
        val clean = rawData.copyOf()
        clean[3] = den[0]; clean[4] = den[1]; clean[5] = den[2]
        return ImuPacket(p.seq, p.tMs, clean, rawData)
    }

    fun reset() = denoiser.reset()
}