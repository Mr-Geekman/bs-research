import re
from copy import copy
from typing import List, Callable, Optional, Any
from string import punctuation


def bool_anti_index(
        bool_list: List[bool],
        list_to_process: List[Any],
) -> List[Any]:
    """Indexing of list according to criteria results.
        Pass the element to new list iff result is False

    :param bool_list: list of bool values
    :param list_to_process: list to process

    :returns: processed list
    """
    processed_list = [
        list_to_process[i]
        for i, res in enumerate(bool_list) if not res
    ]
    return processed_list


class IterativeSpellChecker:
    """Class that makes spell checking with iterative refinement."""

    def __init__(
            self,
            candidate_generator: Callable,
            position_selector: Callable,
            candidate_scorer: Callable,
            tokenizer: Callable,
            detokenizer: Callable,
            max_it: int = 5,
            ignore_titles: bool = True,
            make_blacklisting: bool = True,
            combine_tokens: bool = False
    ):
        """Init object

        :param candidate_generator: model for candidate generation
        :param position_selector: model for selection position of correction
        :param candidate_scorer: model for scoring candidates in position
        :param tokenizer: tokenizer for input sentences
        :param detokenizer: detokenizer for output sentences
        :param max_it: maximum number of iterations
        :param ignore_titles: ignore titled words in correction
        :param make_blacklisting: use or not to use black lists
            for positions in that we failed to make correction
        :param combine_tokens: combine consecutive tokens into one or not
        """
        self.candidate_generator = candidate_generator
        self.position_selector = position_selector
        self.candidate_scorer = candidate_scorer
        self.tokenizer = tokenizer
        self.detokenizer = detokenizer
        self.max_it = max_it
        self.make_blacklisting = make_blacklisting
        self.ignore_titles = ignore_titles
        self.combine_tokens = combine_tokens

    def __call__(
            self, sentences: List[str],
            callback_candidate_scorer: Optional[Callable] = None
    ) -> List[str]:
        """Make corrections for sentences.

        :param sentences: list of sentences
        :param callback_candidate_scorer: some function
            to call after candidate scorer

        :returns: list of corrected sentences
        """
        # make tokenization and basic preprocessing
        tokenized_sentences_cased = [
            self.tokenizer(
                sentence.replace('ё', 'е').replace('Ё', 'Е').replace(
                    '«', '"'
                ).replace('»', '"')
            )
            for sentence in sentences
        ]
        # make lowercase
        tokenized_sentences = [
            [x.lower() for x in sentence]
            for sentence in tokenized_sentences_cased
        ]

        # find correction for each token and their scores
        candidates = self.candidate_generator(
            tokenized_sentences_cased
        )

        # combine tokens if necessary
        if self.combine_tokens:
            results_combination = self.candidate_generator.combine_tokens(
                candidates
            )
            candidates, indices_combined = results_combination

            # combine tokens according to indices_combined
            tokenized_sentences_new = []
            for num_sent, tokenized_sentence in enumerate(tokenized_sentences):
                tokenized_sentence_new = [
                    ' '.join([tokenized_sentence[idx] for idx in list_idx])
                    for list_idx in indices_combined[num_sent]
                ]
                tokenized_sentences_new.append(tokenized_sentence_new)
            tokenized_sentences = tokenized_sentences_new
        else:
            indices_combined = [
                [[idx] for idx in range(len(tokenized_sentence))]
                for tokenized_sentence in tokenized_sentences
            ]

        # list of results
        corrected_sentences = [[] for _ in range(len(tokenized_sentences))]
        # indices of processed sentences
        indices_processing_sentences = list(range(len(tokenized_sentences)))

        # creating black lists
        # initial black list of positions
        if self.ignore_titles:
            initial_black_lists = [
                {i for i, token in enumerate(sentence_start)
                 if i != 0 and token.istitle()}
                for sentence_start in tokenized_sentences_cased
            ]
        else:
            initial_black_lists = [
                set() for _ in range(len(tokenized_sentences))
            ]
        positions_black_lists = copy(initial_black_lists)

        # start iteration procedure
        for cur_it in range(self.max_it):
            # find the best positions for corrections
            best_positions, criteria_results = self.position_selector(
                tokenized_sentences, candidates,
                positions_black_lists
            )

            # finish some sentences
            self._finish_sentences(
                criteria_results, tokenized_sentences,
                indices_processing_sentences, corrected_sentences
            )
            indices_processing_sentences = bool_anti_index(
                criteria_results, indices_processing_sentences
            )
            tokenized_sentences = bool_anti_index(criteria_results,
                                                  tokenized_sentences)
            positions_black_lists = bool_anti_index(criteria_results,
                                                    positions_black_lists)
            candidates = bool_anti_index(criteria_results, candidates)
            best_positions = bool_anti_index(criteria_results, best_positions)
            indices_combined = bool_anti_index(criteria_results,
                                               indices_combined)
            # if all sentences was processed before reaching max_it
            if len(tokenized_sentences) == 0:
                break

            # make scoring of candidates and get scoring info if necessary
            candidate_scorer_results = self.candidate_scorer(
                tokenized_sentences, best_positions, candidates,
                return_scoring_info=(callback_candidate_scorer is not None)
            )
            best_candidates_indices = candidate_scorer_results[0]
            scoring_results = candidate_scorer_results[1]
            scoring_info = candidate_scorer_results[2]

            # make callback if needed
            if callback_candidate_scorer:
                callback_candidate_scorer(
                    tokenized_sentences,
                    indices_processing_sentences, indices_combined,
                    candidates, best_positions,
                    scoring_results, scoring_info
                )

            # make best corrections
            for i in range(len(tokenized_sentences)):
                best_index = best_candidates_indices[i]
                candidate_list = candidates[i][
                    best_positions[i]
                ]
                best_candidate = candidate_list[best_index]['token']
                tokenized_sentences[i][best_positions[i]] = best_candidate

                # make swap of candidates to make current token have index 0
                candidate_list[0]['is_current'] = False
                candidate_list[best_index]['is_current'] = True
                candidate_list[best_index], candidate_list[0] = (
                    candidate_list[0],
                    candidate_list[best_index]
                )

            # update black lists of positions
            if self.make_blacklisting:
                for i, best_index in enumerate(best_candidates_indices):
                    # if current token was selected then we should skip this
                    # position on next iteration
                    if best_index == 0:
                        positions_black_lists[i].add(best_positions[i])
                    # if not current token was selected then we should
                    # clear black list to review all positions in new context
                    else:
                        positions_black_lists[i] = copy(initial_black_lists[i])

        # process remain sentences if they aren't finished
        for i in range(len(tokenized_sentences)):
            idx = indices_processing_sentences[i]
            corrected_sentences[idx] = tokenized_sentences[i]

        # remove punctuation from sentences
        postprocessed_sentences = [
            [x for x in sentence
             if not re.fullmatch('[' + punctuation + ']+', x)]
            for sentence in corrected_sentences
        ]

        # return current detokenized sentences
        return [
            self.detokenizer(sentence) for sentence in postprocessed_sentences
        ]

    def _finish_sentences(
            self, criteria_results: List[bool],
            tokenized_sentences: List[List[str]],
            indices_processing_sentences: List[int],
            corrected_sentences: List[List[str]]
    ) -> None:
        """Finish sentences according to result of stopping criteria.

        :param criteria_results: results of stopping criteria
        :param tokenized_sentences: list of tokenized sentences
        :param indices_processing_sentences: indices  of current
            processing sentences in initial list of processing sentences
        :param corrected_sentences: finished tokenized sentences
            (it is updated in this method)
        """
        for i in range(len(tokenized_sentences)):
            idx = indices_processing_sentences[i]
            if criteria_results[i]:
                corrected_sentences[idx] = tokenized_sentences[i]
