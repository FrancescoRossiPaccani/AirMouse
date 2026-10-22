class GestureRecognizer {
    fun onGesture(window: List<ImuPacket>) {
        println("Sono un gesto (${window.size} campioni)")
    }
}