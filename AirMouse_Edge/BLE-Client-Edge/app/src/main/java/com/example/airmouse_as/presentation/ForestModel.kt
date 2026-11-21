package com.example.airmouse_as.presentation

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class Prediction(val label: String, val confidence: Double)

// Random Forest caricata da assets/rf.json  
class ForestModel private constructor(
    private val classes: List<String>,
    private val nCandidates: Int,
    private val selected: IntArray,
    private val trees: List<Tree>,
) {
    private class Tree(
        val left: IntArray,
        val right: IntArray,
        val feat: IntArray,
        val thr: DoubleArray,
        val proba: Array<DoubleArray>,
    )

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
        for (c in 1 until acc.size) if (acc[c] > acc[best]) best = c
        return Prediction(classes[best], acc[best] / trees.size)
    }

    companion object {
        fun loadFromAsset(context: Context, filename: String = "rf.json"): ForestModel {
            val root = JSONObject(context.assets.open(filename).bufferedReader().use { it.readText() })
            return ForestModel(
                classes = root.getJSONArray("classes").let { a -> List(a.length()) { a.getString(it) } },
                nCandidates = root.getInt("n_candidates"),
                selected = root.getJSONArray("selected").toIntArray(),
                trees = root.getJSONArray("trees").let { a ->
                    List(a.length()) { i ->
                        val t = a.getJSONObject(i)
                        Tree(
                            left = t.getJSONArray("left").toIntArray(),
                            right = t.getJSONArray("right").toIntArray(),
                            feat = t.getJSONArray("feat").toIntArray(),
                            thr = t.getJSONArray("thr").let { v -> DoubleArray(v.length()) { v.getDouble(it) } },
                            proba = t.getJSONArray("proba").let { p ->
                                Array(p.length()) { r ->
                                    val row = p.getJSONArray(r)
                                    DoubleArray(row.length()) { row.getDouble(it) }
                                }
                            },
                        )
                    }
                },
            )
        }

        private fun JSONArray.toIntArray() = IntArray(length()) { getInt(it) }
    }
}
