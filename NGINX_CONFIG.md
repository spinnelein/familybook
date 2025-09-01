# Nginx Configuration for Familybook

When deploying Familybook behind nginx at a subdirectory (e.g., `/familybook`), you need to ensure nginx properly proxies requests to the Flask application.

## Example Nginx Configuration

```nginx
location /familybook {
    # Remove the /familybook prefix before passing to Flask
    rewrite ^/familybook(/.*)$ $1 break;
    
    # Proxy to Flask app (adjust port as needed)
    proxy_pass http://127.0.0.1:5000;
    
    # Important headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Script-Name /familybook;
    
    # For file uploads
    client_max_body_size 100M;
}

# Serve static files directly (more efficient)
location /familybook/static {
    alias /path/to/familybook/static;
}

location /familybook/uploads {
    alias /path/to/familybook/static/uploads;
}
```

## Alternative Configuration (without rewrite)

If you're using the Flask URL prefix configuration:

```nginx
location /familybook {
    proxy_pass http://127.0.0.1:5000/familybook;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 100M;
}
```

## Debugging Tips

1. Check nginx error logs: `sudo tail -f /var/log/nginx/error.log`
2. Check Flask app logs to see if requests are reaching it
3. Test with curl: `curl -X POST http://home.slugranch.org/familybook/upload-multiple-media`
4. Verify Flask is running and listening on the expected port

## Common Issues

1. **404 errors**: Usually means nginx isn't properly routing to Flask
2. **502 Bad Gateway**: Flask app isn't running or wrong port
3. **413 Request Entity Too Large**: Need to increase `client_max_body_size`