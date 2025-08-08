import os
import uuid
import logging
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from config import settings
import ocr_processor
import ai_analyzer
import report_generator

# In a real app, you would have a database module like this:
# import database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Invoice Analysis API",
    description="An API to analyze utility bills, extract data, and generate reports.",
    version="1.0.0"
)


@app.post("/analyze-invoice/")
async def analyze_invoice_endpoint(
        background_tasks: BackgroundTasks,
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: str = Form(...),
        invoice_file: UploadFile = File(...)
):
    """
    This endpoint receives user information and an invoice file, then performs a full analysis.

    1. Saves the uploaded file.
    2. Extracts text using OCR.
    3. Gets a structured analysis from an AI model.
    4. Generates two PDF reports (user-facing and internal).
    5. Returns a summary and a link to the user-facing report.
    """
    logger.info(f"Received invoice for analysis from user: {email}")

    # --- 1. Save Uploaded File ---
    file_extension = os.path.splitext(invoice_file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(settings.UPLOADS_DIR, unique_filename)

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(await invoice_file.read())
        logger.info(f"File saved locally to: {file_path}")
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Could not save file.")

    # --- 2. Extract Text ---
    raw_text = ocr_processor.extract_text(file_path, invoice_file.content_type)
    if not raw_text:
        raise HTTPException(status_code=422,
                            detail="Could not extract text from the document. It might be a blank or corrupted file.")

    # --- 3. Get AI Analysis ---
    # This is an async function, so we await it.
    analysis_data = await ai_analyzer.analyze_invoice_text(raw_text)
    if not analysis_data:
        raise HTTPException(status_code=500, detail="Failed to get analysis from AI model. Please try again later.")

    # --- 4. Generate PDF Reports (in the background) ---
    report_uuid = uuid.uuid4()
    user_report_path = os.path.join(settings.REPORTS_DIR, f"report_{report_uuid}.pdf")
    internal_report_path = os.path.join(settings.INTERNAL_REPORTS_DIR, f"report_internal_{report_uuid}.pdf")

    # We use background tasks so the user gets a fast initial response.
    # The PDF generation happens after the response has been sent.
    background_tasks.add_task(report_generator.create_report_pdf, analysis_data, user_report_path, anonymize=True)
    background_tasks.add_task(report_generator.create_report_pdf, analysis_data, internal_report_path, anonymize=False)

    logger.info("PDF generation tasks scheduled in the background.")

    # --- 5. (Simulated) Database Interaction & Email ---
    # In a real application, you would save the user and invoice details to your database here.
    # You would also trigger an email to the user with the report.
    # database.create_user(first_name, last_name, email)
    # database.save_invoice_record(user_id, file_path, user_report_path, internal_report_path)
    # email_service.send_report(email, user_report_path)

    # --- 6. Return Response ---
    # The URL would point to where the file is served. For local testing, this is just the path.
    # In production, this would be a public URL from your cloud storage.
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Analysis complete. The report will be generated and sent to your email shortly.",
            "popup_summary": analysis_data.get("popup_summary", "Analysis summary is being generated."),
            "report_url": f"/reports/report_{report_uuid}.pdf"  # Example URL
        }
    )


# You would also need an endpoint to serve the generated reports
# This is a simplified example for local testing.
from fastapi.staticfiles import StaticFiles

app.mount("/reports", StaticFiles(directory=settings.REPORTS_DIR), name="reports")

if __name__ == "__main__":
    import uvicorn

    # To run the app: uvicorn main:app --reload
    uvicorn.run(app, host="0.0.0.0", port=8000)
