@echo off
rem Train the spoiler model on the Kaggle data in ..\mltraining, then evaluate it. Run from the backend folder (venv active).
rem First run: use a subsample (150k reviews). Remove --max-reviews for the full ~570k.
python -m ml.train_ml --reviews ..\mltraining\IMDB_reviews.json --movies ..\mltraining\IMDB_movie_details.json --out models --max-reviews 150000
python -m ml.eval_shield --reviews ..\mltraining\IMDB_reviews.json --movies ..\mltraining\IMDB_movie_details.json --models models
python -m scripts.import_kaggle --movies ..\mltraining\IMDB_movie_details.json --limit 300
