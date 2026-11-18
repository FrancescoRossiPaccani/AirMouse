
class SamplePreprocessor(private val denoiseOnPc: Boolean) {
    private val denoiser = WaveletDenoiser(nChannels = 3)

    fun process(p: ImuPacket): ImuPacket {
        if (!denoiseOnPc) return p
        val den = denoiser.update(p.gyro) ?: p.gyro   // finché non è pieno: grezzo
        return ImuPacket(p.seq, p.tMs, den)
    }

    fun reset() = denoiser.reset()
}