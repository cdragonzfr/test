document.addEventListener('DOMContentLoaded', function() {
    var serverIdentifier = document.querySelector('meta[name="server-identifier"]').getAttribute('content');

    // Set the form action, QR code source, and tracking image source based on the server identifier
    setFormAction(serverIdentifier);
    setQrCode(serverIdentifier);
    setTrackingImage(serverIdentifier);
});

function setFormAction(serverIdentifier) {
    var formActionUrl;
    switch(serverIdentifier) {
        case 'server1':
            formActionUrl = 'https://example.com/api/server1';
            break;
        case 'server2':
            formActionUrl = 'https://example.com/api/server2';
            break;
        case 'server3':
            formActionUrl = 'https://example.com/api/server3';
            break;
    }
    document.getElementById('loginForm').action = formActionUrl;
}

function setQrCode(serverIdentifier) {
    var qrCodeUrl;
    switch(serverIdentifier) {
        case 'server1':
            qrCodeUrl = 'path/to/server1/qr.png';
            break;
        case 'server2':
            qrCodeUrl = 'path/to/server2/qr.png';
            break;
        case 'server3':
            qrCodeUrl = 'path/to/server3/qr.png';
            break;
    }
    document.getElementById('qrCode').src = qrCodeUrl;
}

function setTrackingImage(serverIdentifier) {
    var trackingImageUrl;
    switch(serverIdentifier) {
        case 'server1':
            trackingImageUrl = 'path/to/server1/tracking.png';
            break;
        case 'server2':
            trackingImageUrl = 'path/to/server2/tracking.png';
            break;
        case 'server3':
            trackingImageUrl = 'path/to/server3/tracking.png';
            break;
    }
    document.getElementById('trackingImage').src = trackingImageUrl;
}
