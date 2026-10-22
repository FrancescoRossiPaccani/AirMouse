class TrackingModule {
    fun onSample(p: ImuPacket) {
        println("Sto facendo tracking (seq=${p.seq})")
    }
}