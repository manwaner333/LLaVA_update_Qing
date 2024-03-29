import torch
import spacy
import pickle
from tqdm import tqdm
from selfcheckgpt.modeling_selfcheck import SelfCheckMQAG, SelfCheckBERTScore, SelfCheckNgram, SelfCheckNLI
nlp = spacy.load("en_core_web_sm")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model_version = 'llava_v15_7b'
mul_path = f'result/self_data/{model_version}_answer_pope_adversarial_new_prompt_responses_denoted_multiple.bin'
answers_file = f'result/self_data/{model_version}_answer_self_check_pope_adversarial_new_prompt_responses_denoted.bin'
with open(mul_path, "rb") as f_mul:
    responses_mul = pickle.load(f_mul)

selfcheck_mqag = SelfCheckMQAG(device=device)  # set device to 'cuda' if GPU is available
selfcheck_bertscore = SelfCheckBERTScore(rescale_with_baseline=True)
selfcheck_ngram = SelfCheckNgram(n=1)  # n=1 means Unigram, n=2 means Bigram, etc.
selfcheck_nli = SelfCheckNLI(device=device)  # set device to 'cuda' if GPU is available

sent_scores_mqags = {}
sent_scores_bertscores = {}
sent_scores_ngrams = {}
sent_scores_nlis = {}

self_check_responses = {}
count = 0


for idx, response in tqdm(responses_mul.items()):

    # if count < 9:
    #     count += 1
    #     continue

    image_id = response['image_id']
    passage = response['old_res']
    sentences = response['sentences']
    labels = response['label']

    # Other samples generated by the same LLM to perform self-check for consistency
    sample0 = response['text'][0]
    sample1 = response['text'][1]
    sample2 = response['text'][2]
    sample3 = response['text'][3]
    sample4 = response['text'][4]

    # (1)
    # --------------------------------------------------------------------------------------------------------------- #
    # SelfCheck-MQAG: Score for each sentence where value is in [0.0, 1.0] and high value means non-factual
    # Additional params for each scoring_method:
    # -> counting: AT (answerability threshold, i.e. questions with answerability_score < AT are rejected)
    # -> bayes: AT, beta1, beta2
    # -> bayes_with_alpha: beta1, beta2
    try:
        sent_scores_mqag = selfcheck_mqag.predict(
            sentences=sentences,               # list of sentences
            passage=passage,                   # passage (before sentence-split)
            sampled_passages=[sample0, sample1, sample2, sample3, sample4], # list of sampled passages
            num_questions_per_sent=5,          # number of questions to be drawn
            scoring_method='bayes_with_alpha', # options = 'counting', 'bayes', 'bayes_with_alpha'
            beta1=0.8, beta2=0.8,            # additional params depending on scoring_method
        )
        # print(sent_scores_mqag)  # 几个句子就有几个分数
        # [0.30990949 0.42376232]
    except:
        print("This is the error of mqag: {}".format(idx))
        sent_len = len(sentences)
        sent_scores_mqag = [None for _ in range(sent_len)]

    # (2)
    # --------------------------------------------------------------------------------------------------------------- #
    # SelfCheck-BERTScore: Score for each sentence where value is in [0.0, 1.0] and high value means non-factual
    try:
        sent_scores_bertscore = selfcheck_bertscore.predict(
            sentences=sentences,                          # list of sentences
            sampled_passages=[sample0, sample1, sample2, sample3, sample4], # list of sampled passages
        )
        # print(sent_scores_bertscore)
        # [0.0695562  0.45590915]
    except:
        print("This is the error of bert: {}".format(idx))
        sent_len = len(sentences)
        sent_scores_bertscore = [None for _ in range(sent_len)]

    # (3)
    # --------------------------------------------------------------------------------------------------------------- #
    # SelfCheck-Ngram: Score at sentence- and document-level where value is in [0.0, +inf) and high value means non-factual
    # as opposed to SelfCheck-MQAG and SelfCheck-BERTScore, SelfCheck-Ngram's score is not bounded
    try:
        sent_scores_ngram = selfcheck_ngram.predict(
            sentences=sentences,
            passage=passage,
            sampled_passages=[sample0, sample1, sample2, sample3, sample4],
        )
    except:
        print("This is the error of Ngram: {}".format(idx))
        sent_len = len(sentences)
        sent_scores_ngram = [None for _ in range(sent_len)]

    # print(sent_scores_ngram)
    # {'sent_level': { # sentence-level score similar to MQAG and BERTScore variant
    #     'avg_neg_logprob': [3.184312, 3.279774],
    #     'max_neg_logprob': [3.476098, 4.574710]
    #     },
    #  'doc_level': {  # document-level score such that avg_neg_logprob is computed over all tokens
    #     'avg_neg_logprob': 3.218678904916201,
    #     'avg_max_neg_logprob': 4.025404834169327
    #     }
    # }


    # (4)
    # --------------------------------------------------------------------------------------------------------------- #
    try:
        sent_scores_nli = selfcheck_nli.predict(
            sentences=sentences,                          # list of sentences
            sampled_passages=[sample0, sample1, sample2, sample3, sample4],  # list of sampled passages
        )
        # print(sent_scores_nli)
        # [0.334014 0.975106 ] -- based on the example above
    except:
        print("This is the error of Nli: {}".format(idx))
        sent_len = len(sentences)
        sent_scores_nli = [None for _ in range(sent_len)]

    response_value = {
        'sent_scores_mqags': sent_scores_mqag,
        'sent_scores_bertscores': sent_scores_bertscore,
        'sent_scores_ngrams': sent_scores_ngram,
        'sent_scores_nlis': sent_scores_nli,
        'labels': labels
    }
    self_check_responses[idx] = response_value

with open(answers_file, 'wb') as file:
    pickle.dump(self_check_responses, file)
