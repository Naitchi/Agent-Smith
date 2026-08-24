1. Parser — extraire le bloc de code d'une réponse texte. Décide : premier ou dernier bloc ? que faire si zéro bloc ?

2. Client LLM — une fonction, entrée (system, messages), sortie str. Clé dans .env.

3. Prompt système — dis au modèle le format attendu, la persistance d'état, et comment terminer.

4. Boucle — appeler, parser, exécuter, réinjecter l'observation. Sortie sur final_answer ou max_steps.

5. Entrée/sortie — brancher MBPPTaskInput en entrée, remplir SolutionOutput et StepMetrics en sortie.

6. Cas dégradés — pas de code dans la réponse, erreur d'exécution, timeout, boucle qui n'aboutit pas.

Ordre conseillé : 1 → 2 → 4, parce que 1 et 2 se testent isolément. 3 est celui que tu itéreras le plus longtemps.

Un principe à garder : rends le LLM et la sandbox injectables dans ta boucle. Ça te permet de tester avec un faux LLM, sans réseau ni tokens.
