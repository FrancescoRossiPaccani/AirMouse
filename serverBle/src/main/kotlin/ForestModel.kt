import java.io.File
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
class Tree(
    val left: IntArray,
    val right: IntArray,
    val feat: IntArray,
    val thr: DoubleArray,
    val proba: Array<DoubleArray>,
)

class Prediction(val label: String, val confidence: Double)

@Serializable
class ForestModel(
    val classes: List<String>,
    @SerialName("n_candidates") val nCandidates: Int,
    val selected: List<Int>,
    val trees: List<Tree>,
) {
    fun predict(candidates: DoubleArray): Prediction {
        require(candidates.size == nCandidates) {
            "Il modello si aspetta $nCandidates feature, ricevute ${candidates.size}"
        }
        // scikit-learn converte l'input in float32 prima del confronto con le soglie
        val x = DoubleArray(selected.size) { candidates[selected[it]].toFloat().toDouble() }

        val acc = DoubleArray(classes.size)
        for (t in trees) {
            var node = 0
            while (t.left[node] != -1) {
                node = if (x[t.feat[node]] <= t.thr[node]) t.left[node] else t.right[node]
            }
            for (c in acc.indices) acc[c] += t.proba[node][c]
        }
        var best = 0
        for (c in 1 until acc.size)
            if (acc[c] > acc[best])
                best = c
        return Prediction(classes[best], acc[best] / trees.size)
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun load(path: String): ForestModel = json.decodeFromString(File(path).readText())
    }
}