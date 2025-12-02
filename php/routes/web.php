<?php

use App\VastAi\Http\Controllers\VastController;

// Simple route-like helpers for running without full Laravel
$controller = new VastController();

if (php_sapi_name() === 'cli-server') {
    // Running with PHP built-in server: route by path
    $path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    header('Content-Type: application/json');
    if ($path === '/search') {
        echo json_encode($controller->search($_GET));
    } elseif ($path === '/create') {
        $payload = json_decode(file_get_contents('php://input'), true) ?: [];
        echo json_encode($controller->create($payload));
    } elseif (preg_match('#^/status/(.+)$#', $path, $m)) {
        echo json_encode($controller->status($m[1]));
    } else {
        echo json_encode(['ok' => true, 'routes' => ['/search', '/create', '/status/{id}']]);
    }
}

