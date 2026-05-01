<?php
/**
 * Plugin Name: Camera Snapshot
 */
if (!defined('ABSPATH')) exit;

function cs_get_token() { return get_option('cs_bearer_token', ''); }
function cs_set_token($token) { update_option('cs_bearer_token', $token); }

add_action('admin_menu', function() {
  add_options_page('Camera Snapshot', 'Camera Snapshot', 'manage_options', 'camera-snapshot', 'cs_admin_page');
});

function cs_admin_page() {
  if (isset($_POST['cs_token'])) cs_set_token(sanitize_text_field($_POST['cs_token']));
  if (isset($_POST['cs_generate'])) cs_set_token(wp_generate_password(48, false, false));
  $token = esc_html(cs_get_token());
  echo '<div class="wrap"><h1>Camera Snapshot</h1><form method="post">';
  echo '<input type="text" name="cs_token" value="'.$token.'" size="60"> ';
  echo '<button class="button button-primary">Gem token</button> ';
  echo '<button class="button" name="cs_generate" value="1">Generér token</button>';
  echo '</form></div>';
}

add_action('rest_api_init', function() {
  register_rest_route('camera-snapshot/v1', '/upload', [
    'methods' => 'POST',
    'callback' => 'cs_upload_cb',
    'permission_callback' => '__return_true',
  ]);
});

function cs_upload_cb($request) {
  $hdr = $request->get_header('authorization');
  $expected = 'Bearer '.cs_get_token();
  if (!$hdr || !hash_equals($expected, $hdr)) return new WP_REST_Response(['error'=>'unauthorized'], 401);
  $body = $request->get_body();
  if (!$body) return new WP_REST_Response(['error'=>'empty body'], 400);
  $upload = wp_upload_dir();
  $dir = trailingslashit($upload['basedir']).'camera-snapshot';
  if (!file_exists($dir)) wp_mkdir_p($dir);
  $file = trailingslashit($dir).'latest.jpg';
  file_put_contents($file, $body);
  return ['ok'=>true, 'url'=>trailingslashit($upload['baseurl']).'camera-snapshot/latest.jpg'];
}

add_shortcode('camera_snapshot', function() {
  $upload = wp_upload_dir();
  $url = trailingslashit($upload['baseurl']).'camera-snapshot/latest.jpg?t='.time();
  return '<img src="'.esc_url($url).'" alt="Camera Snapshot" />';
});
