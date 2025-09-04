#!/usr/bin/env python3
"""
Test script to verify all endpoints return expected HTTP status codes.
This script tests the refactored FamilyBook application endpoints.
"""

import requests
import time
import json
from urllib.parse import urljoin

class EndpointTester:
    def __init__(self, base_url="http://127.0.0.1:5000"):
        self.base_url = base_url
        self.results = []
        self.test_magic_token = "test_token_123"  # Replace with valid token if available

    def test_endpoint(self, endpoint, expected_status=200, method="GET", data=None):
        """Test a single endpoint and record the result."""
        url = urljoin(self.base_url, endpoint)
        
        try:
            if method == "GET":
                response = requests.get(url, timeout=5, allow_redirects=False)
            elif method == "POST":
                response = requests.post(url, data=data, timeout=5, allow_redirects=False)
            
            status_code = response.status_code
            passed = status_code == expected_status
            
            # Check for common server errors in response content
            error_indicators = []
            if status_code >= 500:
                response_text = response.text.lower()
                if 'builderror' in response_text:
                    error_indicators.append("BuildError (template URL issue)")
                if 'traceback' in response_text:
                    error_indicators.append("Server exception")
                if 'werkzeug debugger' in response_text:
                    error_indicators.append("Werkzeug error page")
            
            result = {
                "endpoint": endpoint,
                "method": method,
                "expected": expected_status,
                "actual": status_code,
                "passed": passed,
                "error": None,
                "error_indicators": error_indicators
            }
            
            self.results.append(result)
            error_info = f" ({', '.join(error_indicators)})" if error_indicators else ""
            print(f"{'PASS' if passed else 'FAIL'} {method} {endpoint} -> {status_code} (expected {expected_status}){error_info}")
            
        except Exception as e:
            result = {
                "endpoint": endpoint,
                "method": method,
                "expected": expected_status,
                "actual": None,
                "passed": False,
                "error": str(e),
                "error_indicators": []
            }
            
            self.results.append(result)
            print(f"ERROR {method} {endpoint} -> ERROR: {e}")

    def run_tests(self):
        """Run all endpoint tests."""
        print("Testing FamilyBook Endpoints")
        print("=" * 50)
        
        # Core application endpoints
        print("\n[HOME] Core Application Endpoints:")
        self.test_endpoint("/")  # Home page
        self.test_endpoint("/about-us")  # About us page
        self.test_endpoint("/posts", expected_status=302)  # Should redirect (no token)
        
        # Posts with magic token (expect 404 for invalid token)
        print("\n[POSTS] Posts Endpoints (with test token):")
        self.test_endpoint(f"/posts/{self.test_magic_token}", expected_status=404)
        self.test_endpoint(f"/create-post/{self.test_magic_token}", expected_status=404)
        self.test_endpoint(f"/photos/{self.test_magic_token}", expected_status=404)
        
        # User interaction endpoints (expect 404 for invalid token)
        print("\n[USER] User Interaction Endpoints:")
        self.test_endpoint(f"/user-settings/{self.test_magic_token}", expected_status=404)
        
        # Admin endpoints (expect redirects or 403)
        print("\n[ADMIN] Admin Endpoints:")
        self.test_endpoint("/admin/login", expected_status=200)
        self.test_endpoint("/admin/console", expected_status=302)  # Should redirect to login
        self.test_endpoint("/admin/settings", expected_status=302)  # Should redirect to login
        self.test_endpoint("/admin/users", expected_status=404)  # Route doesn't exist
        self.test_endpoint("/admin/activity-log", expected_status=302)  # Should redirect to login
        self.test_endpoint("/admin/email-logs", expected_status=302)  # Should redirect to login
        
        # Media upload endpoints
        print("\n[MEDIA] Media Endpoints:")
        self.test_endpoint("/upload-media", expected_status=405, method="GET")  # POST only
        self.test_endpoint("/upload-multiple-images", expected_status=405, method="GET")  # POST only
        
        # Google Photos API endpoints
        print("\n[PHOTOS] Google Photos API Endpoints:")
        self.test_endpoint("/api/google-photos/create-session", expected_status=405, method="GET")  # POST only
        self.test_endpoint("/google-photos/auth", expected_status=302)  # Should redirect
        
        # Static file serving (test with a likely non-existent file)
        print("\n[FILES] File Serving Endpoints:")
        self.test_endpoint("/uploads/nonexistent.jpg", expected_status=404)
        
        # Summary
        print("\n" + "=" * 50)
        self.print_summary()

    def print_summary(self):
        """Print test summary."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        
        print(f"[SUMMARY] Test Summary:")
        print(f"   Total endpoints tested: {total}")
        print(f"   PASSED: {passed}")
        print(f"   FAILED: {failed}")
        print(f"   Success rate: {(passed/total)*100:.1f}%")
        
        if failed > 0:
            print(f"\n[FAILED] Failed tests:")
            for result in self.results:
                if not result["passed"]:
                    error = f" ({result['error']})" if result['error'] else ""
                    indicators = f" - {', '.join(result['error_indicators'])}" if result.get('error_indicators') else ""
                    print(f"   {result['method']} {result['endpoint']} -> {result['actual']} (expected {result['expected']}){error}{indicators}")

if __name__ == "__main__":
    print("Starting endpoint tests...")
    print("Make sure the Flask application is running on http://127.0.0.1:5000")
    print("Waiting 3 seconds for application to be ready...")
    time.sleep(3)
    
    tester = EndpointTester()
    tester.run_tests()