import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash
from azure.data.tables import TableServiceClient, TableClient
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from opencensus.ext.azure.log_exporter import AzureLogHandler
import logging

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# Azure connection strings from environment variables
STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
APPINSIGHTS_CONNECTION_STRING = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
TABLE_NAME = "products"
CONTAINER_NAME = "product-images"

# App Insights logging
if APPINSIGHTS_CONNECTION_STRING:
    logger = logging.getLogger(__name__)
    logger.addHandler(AzureLogHandler(connection_string=APPINSIGHTS_CONNECTION_STRING))
    logger.setLevel(logging.INFO)

def get_table_client():
    service = TableServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
    try:
        service.create_table(TABLE_NAME)
    except ResourceExistsError:
        pass
    return service.get_table_client(TABLE_NAME)

def get_blob_client():
    service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
    try:
        service.create_container(CONTAINER_NAME)
    except ResourceExistsError:
        pass
    return service

def upload_image(file):
    if not file or file.filename == "":
        return None
    blob_service = get_blob_client()
    ext = file.filename.rsplit(".", 1)[-1].lower()
    blob_name = f"{uuid.uuid4()}.{ext}"
    blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=blob_name)
    blob_client.upload_blob(file.read(), overwrite=True)
    return blob_client.url

def delete_image_by_url(url):
    if not url:
        return
    blob_name = url.split("/")[-1]
    blob_service = get_blob_client()
    blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=blob_name)
    try:
        blob_client.delete_blob()
    except Exception:
        pass

@app.route("/")
def index():
    table = get_table_client()
    products = list(table.list_entities())
    return render_template("index.html", products=products)

@app.route("/add", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", "").strip()
        description = request.form.get("description", "").strip()
        image_file = request.files.get("image")

        if not name or not price:
            flash("Name and price are required.", "danger")
            return render_template("form.html", action="Add", product=None)

        image_url = upload_image(image_file) if image_file else None
        product_id = str(uuid.uuid4())

        table = get_table_client()
        table.create_entity({
            "PartitionKey": "product",
            "RowKey": product_id,
            "Name": name,
            "Price": price,
            "Description": description,
            "ImageUrl": image_url or ""
        })
        flash("Product added successfully!", "success")
        return redirect(url_for("index"))
    return render_template("form.html", action="Add", product=None)

@app.route("/edit/<product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    table = get_table_client()
    product = table.get_entity(partition_key="product", row_key=product_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", "").strip()
        description = request.form.get("description", "").strip()
        image_file = request.files.get("image")

        if not name or not price:
            flash("Name and price are required.", "danger")
            return render_template("form.html", action="Edit", product=product)

        image_url = product.get("ImageUrl", "")
        if image_file and image_file.filename != "":
            delete_image_by_url(image_url)
            image_url = upload_image(image_file)

        table.update_entity({
            "PartitionKey": "product",
            "RowKey": product_id,
            "Name": name,
            "Price": price,
            "Description": description,
            "ImageUrl": image_url or ""
        }, mode="replace")
        flash("Product updated successfully!", "success")
        return redirect(url_for("index"))

    return render_template("form.html", action="Edit", product=product)

@app.route("/delete/<product_id>", methods=["POST"])
def delete_product(product_id):
    table = get_table_client()
    product = table.get_entity(partition_key="product", row_key=product_id)
    delete_image_by_url(product.get("ImageUrl"))
    table.delete_entity(partition_key="product", row_key=product_id)
    flash("Product deleted.", "warning")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8000)
