import os
import uuid

import duckdb
import torch
import dill
from lester.save_artifacts import _save_as_json, _persist_with_row_provenance, matrix_column_provenance_as_json, _persist_matrices
from lester.feature_provenance import _matrix_column_provenance
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score


def instantiate(function_name, transformed_code):
    variables_for_exec = {}
    exec(transformed_code, variables_for_exec)
    return variables_for_exec[function_name]


def run_pipeline(name, source_paths, _lester_dataprep, encode_features, extract_label,
                 __model, random_seed=42):
    run_id = uuid.uuid4()
    artifact_path = f'.lester/{name}/{run_id}'
    os.makedirs(artifact_path)

    run_id = uuid.uuid4()
    artifact_path = f'.lester/{name}/{run_id}'
    os.makedirs(artifact_path)

    print(f"Starting lester run ({artifact_path})")
    _save_as_json(f'{artifact_path}/source_paths.json', source_paths)

    tracked_df = _lester_dataprep(**source_paths)

    prepared_data = tracked_df.df
    prov_columns = ','.join(tracked_df.row_provenance_columns)
    print("Rows after data preparation:", len(prepared_data))

    intermediate_train, intermediate_test = \
        train_test_split(prepared_data, test_size=0.2, random_state=random_seed)
    _persist_with_row_provenance(intermediate_train, intermediate_test, prov_columns, artifact_path)
    train_df = duckdb.query(f"SELECT * EXCLUDE {prov_columns} FROM intermediate_train").to_df()
    test_df = duckdb.query(f"SELECT * EXCLUDE {prov_columns} FROM intermediate_test").to_df()

    column_provenance = tracked_df.column_provenance
    _save_as_json(f'{artifact_path}/column_provenance.json', column_provenance)

    feature_transformer = encode_features()
    feature_transformer = feature_transformer.fit(train_df)

    matrix_column_provenance = _matrix_column_provenance(feature_transformer)
    _save_as_json(f'{artifact_path}/matrix_column_provenance.json',
                  matrix_column_provenance_as_json(matrix_column_provenance))

    X_train = feature_transformer.transform(train_df)
    y_train = extract_label(train_df)

    num_samples = X_train.shape[0]
    num_features = X_train.shape[1]

    print(f"Training data: {num_samples} samples with {num_features} features")

    from skorch import NeuralNetBinaryClassifier
    model, loss = __model(num_features)

    learner = NeuralNetBinaryClassifier(
        model,
        max_epochs=25,
        lr=0.001,
        iterator_train__shuffle=True,
        criterion=loss,
        optimizer=torch.optim.Adam,
    )

    trained_model = learner.fit(
         torch.from_numpy(X_train).float(),
         torch.from_numpy(y_train).float()
    )

    X_test = feature_transformer.transform(test_df)
    y_test = extract_label(test_df)

    y_pred = trained_model.predict(torch.from_numpy(X_test).float())
    print(accuracy_score(y_test, y_pred))

    _persist_matrices(X_train, y_train, X_test, y_test, y_pred, artifact_path)
    torch.save(trained_model.module_, f"{artifact_path}/model.pt", pickle_module=dill)