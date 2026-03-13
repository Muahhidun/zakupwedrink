const assert = require('assert');

let yesterdayStock = {3: 13.0};
let todaySupplies = {3: 0};
let products = [{id: 3, name_internal: 'Orange', package_weight: 2.6, unit: 'kg', units_per_box: 8}];

function getHtml(initialValues = null) {
    let output = '';
    products.forEach(p => {
        const yest = yesterdayStock[p.id] || 0;
        const supp = todaySupplies[p.id] || 0;
        const expected = yest + supp;
        const expectedDisplay = expected > 0 ? expected.toFixed(1) : '-';

        let inputValue = '0';
        if (initialValues && initialValues[p.id] !== undefined) {
            inputValue = initialValues[p.id];
        }

        output += `<input value="${inputValue}">`;
    });
    return output;
}

console.log("Without initial:", getHtml());
console.log("With initial:", getHtml({3: 12.0}));
