Run as standalone microservice (quick):

1. Install dependencies: composer install
2. Start built-in server: php -S 127.0.0.1:8080 -t php php/routes/web.php
3. Browse: http://127.0.0.1:8080/search

Or integrate into Laravel by copying `app/` into your app namespace and registering service provider.

