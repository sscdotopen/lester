import os
from dateutil import parser
from transformers import pipeline
os.environ["TOKENIZERS_PARALLELISM"] = "False"
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)


def messy_pipeline(customers_path, mails_path):
    target_countries = ['UK', 'DE', 'FR']
    customer_data = {}

    sentiment_predictor = pipeline('sentiment-analysis', model='distilbert-base-uncased-finetuned-sst-2-english')

    def sanitize(text):
        return text.lower()

    with open(".scratchspace/__intermediate.csv", 'w') as output_file:
        with open(customers_path) as file:
            for line in file:
                parts = line.strip().split(',')
                customer_id, customer_email, bank, country, level = parts
                is_premium = (level == 'premium')
                if country in target_countries:
                    customer_data[customer_email] = (bank, country, is_premium)

        with open(mails_path) as file:
            for line in file:
                parts = line.strip().split(",")
                mail_id, email, raw_date, mail_subject, mail_text = parts
                mail_date = parser.parse(raw_date)
                if mail_date.year >= 2022:
                    if email in customer_data:
                        bank, country, is_premium = customer_data[email]
                        title = sanitize(mail_subject)
                        text = sanitize(mail_text)
                        sentiment = sentiment_predictor(mail_text)[0]['label'].lower()
                        output_file.write(f"{title}\t{text}\t{bank}\t{country}\t{sentiment}\t{is_premium}\n")


    import numpy as np
    from sentence_transformers import SentenceTransformer

    sentence_embedder = SentenceTransformer("all-mpnet-base-v2")

    def count_words(text):
        return len(text.split(" "))

    country_indices = {'DE': 0, 'FR': 1, 'UK': 2}

    titles = []
    title_lengths = []
    texts = []
    countries = []


    with open(".scratchspace/__intermediate.csv") as file:
        for line in file:
            parts = line.strip().split("\t")
            title, text, bank, country, sentiment, is_premium = parts

            titles.append(title)
            title_lengths.append(len(title))
            texts.append(text)
            countries.append(country)

    print('### Embedding titles')
    subject_embeddings = sentence_embedder.encode(titles)
    print('### Embedding mails')
    text_embeddings = sentence_embedder.encode(texts)
    title_lengths_column = np.array(title_lengths)
    title_lengths_column = (title_lengths_column - np.mean(title_lengths_column)) / np.std(title_lengths_column)

    country_onehot = np.zeros((len(countries), len(country_indices)))
    for row, country in enumerate(countries):
        country_onehot[row, country_indices[country]] = 1.0


    X = np.concatenate((
        subject_embeddings,
        text_embeddings,
        title_lengths_column.reshape(-1,1),
        country_onehot
    ), axis=1)


    labels = []
    with open(".scratchspace/__intermediate.csv") as file:
        for line in file:
            parts = line.strip().split("\t")
            title, text, bank, country, sentiment, is_premium = parts

            label = 0.0
            if sentiment == 'negative' and is_premium == 'True':
                label = 1.0
            labels.append(label)

    y = np.array(labels)

    from sklearn.linear_model import SGDClassifier
    model = SGDClassifier(loss="log_loss", penalty=None)
    model.fit(X, y)

    np.save(f'.scratchspace/X_train.npy', X)
    np.save(f'.scratchspace/y_train.npy', y)

    import dill
    with open('.scratchspace/model.pkl', 'wb') as model_file:
        dill.dump(model, model_file)


if __name__ == '__main__':
    import argparse
    import time

    argparser = argparse.ArgumentParser(description='Retraining experiments')
    argparser.add_argument('--num_customers', required=True)
    argparser.add_argument('--num_repetitions', required=True)
    args = argparser.parse_args()

    customers_path = f"data/synthetic_customers_{args.num_customers}.csv"
    mails_path = f"data/synthetic_mails_{args.num_customers}.csv"

    for repetition in range(0, int(args.num_repetitions)):
        print(f"# Starting repetition {repetition+1}/{args.num_repetitions} with {args.num_customers} customers")
        start = time.time()
        messy_pipeline(customers_path, mails_path)
        runtime_in_ms = int((time.time() - start) * 1000)
        print(f"{args.num_customers},{runtime_in_ms}")