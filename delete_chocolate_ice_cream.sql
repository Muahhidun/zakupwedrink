-- Удаление дубликата товара "Шоколадное мороженое"
-- Этот товар дублирует "Порошок со вкусом молочного коктейля (шоколадный) 3кг"

-- Показать информацию о товаре перед удалением
SELECT
    id,
    name_ru,
    name_cn,
    (SELECT COUNT(*) FROM stock WHERE product_id = products.id) as stock_count,
    (SELECT COUNT(*) FROM supplies WHERE product_id = products.id) as supply_count
FROM products
WHERE name_ru = 'Шоколадное мороженое';

-- Удалить связанные записи остатков
DELETE FROM stock
WHERE product_id IN (
    SELECT id FROM products WHERE name_ru = 'Шоколадное мороженое'
);

-- Удалить связанные записи поставок
DELETE FROM supplies
WHERE product_id IN (
    SELECT id FROM products WHERE name_ru = 'Шоколадное мороженое'
);

-- Удалить сам товар
DELETE FROM products
WHERE name_ru = 'Шоколадное мороженое';

-- Показать результат
SELECT COUNT(*) as remaining_count
FROM products
WHERE name_ru LIKE '%шоколад%' OR name_ru LIKE '%мороженое%';
