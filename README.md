# Visual Inspection

A web application that checks images of a metal plate with a supplied Computer Vision classifier, records each inspection, processes image batches in the background, and lets a Supervisor confirm or correct each result.

Built for Round 2 of the Python Full Stack and AI Hackathon.

The images and model are educational demonstrations, not a real factory inspection tool.

## What each role can do

| Role | Can do | Cannot do |
| --- | --- | --- |
| Administrator | Register and view products | Submit images or review |
| Engineer | Inspect one image or a batch, and see their own history | Review results, or see other Engineers' results |
| Supervisor | See all inspections, filter them, confirm or correct results, and see metrics | Submit images |

Roles are enforced by the backend. For example, an Engineer calling the review API directly gets `403 Forbidden`.

## Technology

| Part | Technology |
| --- | --- |
| Screens | HTML, CSS, JavaScript, Bootstrap |
| Backend and APIs | Django, Django REST Framework |
| Database | PostgreSQL |
| Background work | Celery, Redis |
| Image handling and model | Pillow, NumPy |
| Tests | Django tests |

## How it works

```text
Browser -> Django REST API -> upload checks -> PostgreSQL and media storage
                                   |
                  One image: run the model straight away
                  Batch: Redis queue -> Celery worker -> run the model
                                   |
                         Save the original result
                                   |
                   Supervisor review, saved separately
```

- **Single image:** the file is checked, then the model runs during the request, and the result is saved and returned.
- **Batch:** the API checks each file and replies straight away. Valid files are `queued`, and the Celery worker processes each one. Invalid files are saved as `failed` with a reason and no prediction, and never reach the model.
- **Status values:** `queued`, `processing`, `completed`, `failed`.
- **Reviews:** a review is a separate record. The model's original output never changes.

## Upload rules

Checks use the file's real content, never its name.

- Decoded JPEG or PNG only
- At most 5 MiB per file
- Each side from 64 to 4096 pixels, inclusive
- 1 to 10 files per batch

## The model

| Item | Value |
| --- | --- |
| Version | `BIT-PLATE-CV-1.0` |
| Product | `P-PLATE01`, Demonstration metal plate |
| Classes | Normal, Defective |
| Type | 17 image features with logistic regression, not a neural network |
| Decision rule | Defective when `defect_probability >= 0.5`, otherwise Normal |
| Confidence shown | Probability of the predicted class |
| Location | `inspections/model/` |

The supplied weights, feature extraction and threshold are unchanged. Filenames, folders and `labels.csv` are never used to make a prediction. `labels.csv` is used only for scoring.

## Results on the 60 labelled samples

Rows are actual labels, and columns are predictions. Defective is the positive class.

| | Predicted Normal | Predicted Defective |
| --- | --- | --- |
| **Actual Normal** | 30 (TN) | 0 (FP) |
| **Actual Defective** | 0 (FN) | 30 (TP) |

**Defect recall = TP / (TP + FN) = 30 / 30 = 100%.**

No false negatives occurred. These results use original model outputs, before any human review, and the 3 Validation files are excluded.

**Limitation:** this is a small synthetic set with fixed framing, so it cannot establish real-world reliability. Real photographs, rotated or displaced plates, different backgrounds and unfamiliar defects are outside the model's validated scope. Confidence is an uncalibrated model score, not a guarantee.

To reproduce the results:

```powershell
python manage.py evaluate_samples
```

This prints the results and saves them to `metrics_report.txt` and `metrics_report.json`.

## Setup on Windows

You need Python, PostgreSQL and Redis.

**1. Get the code and install packages**

```powershell
git clone https://github.com/Sanika1356/VisualInspection.git
cd VisualInspection
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**2. Create the database**

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE visual_inspection;"
```

Change the version number in the path if yours is different.

**3. Create your settings file**

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `DB_PASSWORD` to your own PostgreSQL password. Never commit `.env`.

**4. Prepare the data**

```powershell
python manage.py migrate
python manage.py load_products
python manage.py seed_demo
python manage.py evaluate_samples
```

## Run the application

Use 3 terminals, and keep them all open. Turn on `.venv` in terminals 2 and 3.

| Terminal | Purpose | Command |
| --- | --- | --- |
| 1 | Redis | `redis-server` |
| 2 | Website | `python manage.py runserver` |
| 3 | Background worker | `celery -A config worker --pool=solo -l info` |

Then open http://127.0.0.1:8000.

- `--pool=solo` is needed for Celery on Windows.
- If you use Redis 5, keep `REDIS_PROTOCOL=2` in `.env`. With Redis 6 or newer, you can use `3`.
- Single inspections do not need Redis or the worker. Batches do.

## Demo logins

These are created by `python manage.py seed_demo`. They are for local demonstration only.

| Username | Role | Password |
| --- | --- | --- |
| `demo_admin` | Administrator | `Demo@12345` |
| `demo_engineer` | Engineer | `Demo@12345` |
| `demo_engineer2` | Engineer | `Demo@12345` |
| `demo_supervisor` | Supervisor | `Demo@12345` |

## API summary

All APIs need a signed-in user. Browser `POST` requests need the `X-CSRFToken` header.

| Method | Address | Who | Purpose |
| --- | --- | --- | --- |
| GET | `/api/csrf/` | Anyone | Set the CSRF cookie |
| POST | `/api/login/` | Anyone | Sign in |
| POST | `/api/logout/` | Signed-in users | Sign out |
| GET | `/api/me/` | Signed-in users | Current user and role |
| GET | `/api/products/` | Signed-in users | List products |
| POST | `/api/products/` | Administrator | Add a product |
| POST | `/api/inspections/` | Engineer | Inspect one image, with `product` and `file` |
| GET | `/api/inspections/` | Engineer (own), Supervisor (all) | History, with `?prediction=` and `?review_status=` |
| GET | `/api/inspections/<id>/` | Engineer (own), Supervisor (all) | One inspection and its review |
| GET | `/api/inspections/<id>/image/` | Engineer (own), Supervisor (all) | The saved image |
| POST | `/api/inspections/<id>/review/` | Supervisor | Confirm or correct, with `reviewed_class` and optional `comment` |
| POST | `/api/batches/` | Engineer | Submit 1 to 10 images, with `product` and `files` |
| GET | `/api/batches/<id>/` | Engineer (own), Supervisor (all) | Batch and per-item status |
| GET | `/api/metrics/` | All three roles | Saved evaluation results |

History filters:

- `prediction`: `Normal` or `Defective`
- `review_status`: `pending`, `confirmed` or `corrected`

## Tests

```powershell
python manage.py test
```

The tests do not need Redis or a running worker. They cover invalid image rejection, Supervisor-only review, result persistence, batch limits, mixed batches, role permissions and login.

## Demonstration steps

1. **Administrator:** show product `P-PLATE01`.
2. **Engineer:** inspect one image from `pack_data/Samples/images`, then reload the page.
3. **Engineer:** upload a batch of valid samples plus the 3 files in `pack_data/Validation`. Valid files complete, and bad ones show a reason.
4. **Supervisor:** filter the history, correct a result with a comment, then reload to show both the original and the review.
5. **Engineer:** attempt a review through the API, and show the `403`.
6. **Supervisor:** explain the confusion matrix, defect recall and the limitation.

## Project layout

```text
config/              Django settings, URLs and Celery setup
inspections/         Models, APIs, pages, upload checks, background task and tests
inspections/model/   Supplied model and inference helper (unchanged)
pack_data/           Supplied samples, labels, validation files and product details
templates/           Page templates
static/              CSS, JavaScript and local Bootstrap
```

## Reused from Round 1

This is a separate project from our Round 1 Manufacturing Manual Assistant. No Round 1 application code was copied in. We reused ideas from Round 1: the same three roles, group-based permissions, a similar REST API and CSRF approach, and demo accounts created by a command. The inspection workflow was built during Round 2.

## Security notes

- Keep `.env` and real secrets out of Git.
- `DEBUG` and the default `SECRET_KEY` are for local demonstration only. Change them before any real deployment.
- Uploaded images are served only through the permission-checked image API.
- Invalid uploads are not stored on disk.
