from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.storage import S3Storage, StorageError


class S3StorageTest(TestCase):
    def setUp(self):
        with patch.dict(
            "os.environ",
            {
                "AWS_ACCESS_KEY_ID": "docmind-test",
                "AWS_SECRET_ACCESS_KEY": "docmind-test-local",
                "AWS_DEFAULT_REGION": "us-east-1",
            },
        ):
            self.storage = S3Storage("docmind-test", "http://127.0.0.1:9000")
        self.stub = self.enterContext(Stubber(self.storage.client))

    def test_put_get_and_delete(self):
        content = b"test content"
        source = BytesIO(content)
        object_args = {"Bucket": "docmind-test", "Key": "owner/document.pdf"}
        self.stub.add_response(
            "put_object",
            {},
            {
                **object_args,
                "Body": source,
                "ContentLength": len(content),
                "ContentType": "application/pdf",
            },
        )
        self.stub.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(content), len(content))},
            object_args,
        )
        self.stub.add_response("delete_object", {}, object_args)

        self.storage.put(object_args["Key"], source, len(content))
        with self.storage.open(object_args["Key"]) as stream:
            self.assertEqual(stream.read(), content)
        self.storage.delete(object_args["Key"])
        self.stub.assert_no_pending_responses()

    def test_storage_errors_are_wrapped(self):
        self.stub.add_client_error(
            "get_object", service_error_code="AccessDenied", http_status_code=403
        )
        with self.assertRaises(StorageError):
            self.storage.open("owner/document.pdf")
