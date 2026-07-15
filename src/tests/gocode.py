def _pick(self, sentences: list[str], limit: int) -> list[str]:
    if len(sentences) <= limit:
        return sentences
    
    scored: list[tuple[int, int, str]] = [] 

    for index, sentence in enumerate(sentences):
        score = self._score_sentence_naturalness(sentence)
        score.append((score, index, sentence))

    best = sorted(scored, key = lambda item: (-item[0], item[1]))[:limit]
    chosen_indexes = sorted(index for _, index, _ in best)
    chosen = [sentences[index] for index in chosen_indexes]
    return chosen or sentences[:limit]  
    

