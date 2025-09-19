<?php

// decode_response.php

// --- Configuration ---
$inputJsonFile = 'response_pdf.json';

echo "Reading response from '{$inputJsonFile}'...\n";

// --- Script ---

// 1. Check if the file exists and is readable
if (!is_readable($inputJsonFile)) {
    die("Error: The file '{$inputJsonFile}' was not found or cannot be read.\n");
}

// 2. Read the file content into a string
$jsonContent = file_get_contents($inputJsonFile);

// 3. Decode the JSON string into an associative array
// The 'true' argument converts JSON objects to associative arrays
$data = json_decode($jsonContent, true);

// Check if JSON decoding was successful
if (json_last_error() !== JSON_ERROR_NONE) {
    die("Error: Invalid JSON format in '{$inputJsonFile}'.\n");
}

// 4. Decode and save the non-anonymous report
if (isset($data['non_anonymous_report_base64'])) {
    // Get the Base64 string from the array
    $nonAnonBase64 = $data['non_anonymous_report_base64'];

    // Decode the string into raw binary data
    $nonAnonBytes = base64_decode($nonAnonBase64);

    // Save the binary data to a new PDF file
    $outputFilenameNonAnon = 'DECODED_non_anonymous_report.php.pdf';
    file_put_contents($outputFilenameNonAnon, $nonAnonBytes);

    echo "✅ Successfully saved '{$outputFilenameNonAnon}'\n";
} else {
    echo "⚠️  'non_anonymous_report_base64' key not found in JSON.\n";
}

// 5. Decode and save the anonymous report
if (isset($data['anonymous_report_base64'])) {
    // Get the Base64 string from the array
    $anonBase64 = $data['anonymous_report_base64'];

    // Decode the string
    $anonBytes = base64_decode($anonBase64);

    // Save the file
    $outputFilenameAnon = 'DECODED_anonymous_report.php.pdf';
    file_put_contents($outputFilenameAnon, $anonBytes);

    echo "✅ Successfully saved '{$outputFilenameAnon}'\n";
} else {
    echo "⚠️  'anonymous_report_base64' key not found in JSON.\n";
}

?>