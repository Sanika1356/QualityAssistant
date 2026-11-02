# AI Visual Quality Inspection

A Django REST Framework application for managing AI-based visual
quality inspection of metal plates.

The system stores inspection results, manages user roles, and allows
Supervisors to review and correct AI predictions without changing
the original model output.

## Technologies Used

- Python 3.11 or newer
- Django
- Django REST Framework
- PostgreSQL
- Pillow and NumPy
- Celery and Redis (for batch-processing integration)

## User Roles

### Administrator
- Manages product information.
- Can add and manage products.
- Has access to Django Admin.

### Engineer
- Uploads inspection images.
- Views their own inspection history.
- Cannot review or modify AI predictions.

### Supervisor
- Views inspection history across engineers.
- Filters inspections by prediction and review status.
- Confirms or corrects completed inspection results.
- Adds review comments.

## Database Models

The application contains four main models:

1. Product – Stores product details.
2. Batch – Stores batch submission information.
3. Inspection – Stores uploaded image details, AI predictions,
   confidence, status, and model version.
4. Review – Stores the Supervisor's independent review.

The original AI prediction is preserved even when a Supervisor
corrects the result.

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET, POST | /api/products/ | List and manage products |
| GET | /api/inspections/ | View inspection history |
| GET | /api/inspections/<id>/ | View inspection details |
| POST | /api/inspections/<id>/review/ | Submit Supervisor review |
| GET | /api/inspections/<id>/image/ | View the saved image, with access checks |
| POST | /api/batches/ | Submit 1 to 10 images for background inspection |
| GET | /api/batches/<id>/ | Follow each batch item's status |

The single-image endpoint is to be integrated by its project module.

## History Filters

Inspection history supports:

- prediction=Normal
- prediction=Defective
- review_status=pending
- review_status=confirmed
- review_status=corrected

Engineers can access only their own inspection records.
Supervisors can access all inspection records.

## Role-Based Permissions

Permissions are enforced on the backend using Django REST Framework
permission classes and Django user groups.

- Administrator: product creation and management.
- Engineer: inspection history access for their own submissions.
- Supervisor: access to all inspection records and review operations.

An Engineer attempting to submit a review receives HTTP 403 Forbidden.

## Running the Project

Activate the virtual environment:

    .venv\Scripts\Activate.ps1

Install dependencies:

    pip install -r requirements.txt

Copy `.env.example` to `.env`, set your PostgreSQL password, and create the
`visual_inspection` database.

Run migrations and load the starting data:

    python manage.py migrate
    python manage.py load_products
    python manage.py seed_demo

Start Redis, then start the background worker in its own terminal:

    celery -A config worker --pool=solo -l info

Start the development server:

    python manage.py runserver

Open:

    http://127.0.0.1:8000/

## Running Tests

Run:

    python manage.py test inspections

The tests cover:

- Engineer can view only their own inspections.
- Supervisor can view all inspections.
- Engineer cannot submit a review.
- Supervisor can review a completed inspection.
- Original AI prediction remains unchanged after review.
- Engineer cannot create products.

## Product Data

Initial demonstration product:

- Product ID: P-PLATE01
- Name: Demonstration metal plate
- Description: Synthetic centered plate with scratches or pits

## Important Notes

The inspection records created manually during development use
placeholder image paths. Actual image validation and model prediction
are part of the image-inspection integration.

Do not commit passwords, secret keys, or real user credentials.

### Demo Accounts

Create the demo users and role groups on a fresh database:

```bash
python manage.py seed_demo
```

| Username | Role | Password |
|---|---|---|
| demo_admin | Administrator | Demo@12345 |
| demo_engineer | Engineer | Demo@12345 |
| demo_supervisor | Supervisor | Demo@12345 |

The command creates the Administrator, Engineer and Supervisor groups and assigns each demo account to its corresponding group.

**Note:** These credentials are intended only for local development and project demonstrations. Do not use them in production.