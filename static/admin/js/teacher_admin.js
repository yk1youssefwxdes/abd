document.addEventListener('DOMContentLoaded', function() {
    const paymentMethodSelect = document.getElementById('id_payment_method');
    if (!paymentMethodSelect) return;

    const rowPercentage = document.querySelector('.field-payment_percentage');
    const rowHourly = document.querySelector('.field-hourly_rate');
    const rowSession = document.querySelector('.field-session_rate');

    function toggleFields() {
        const val = paymentMethodSelect.value;
        if (rowPercentage) {
            rowPercentage.style.display = val === 'PERCENTAGE' ? '' : 'none';
        }
        if (rowHourly) {
            rowHourly.style.display = val === 'HOURLY' ? '' : 'none';
        }
        if (rowSession) {
            rowSession.style.display = val === 'SESSION' ? '' : 'none';
        }
    }

    paymentMethodSelect.addEventListener('change', toggleFields);
    toggleFields(); // Run once on page load to initialize field visibility
});
