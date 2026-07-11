-- OreX Seed Data - 9 Minecraft Ores

INSERT INTO ores (name, description, icon_filename, current_price, base_price, price_floor, price_ceiling, volatility, price_change_range, base_probabilities, trend_log)
VALUES
    ('Coal', 'Stable, low value. A reliable fuel source found abundantly throughout the world.', 'Coal.webp', 10.00, 10.00, 2.00, 50.00, 0.5, '[2, 5]', '[25, 60, 15]', '["hold","hold","hold","hold","hold"]'),
    ('Iron', 'Reliable, moderate. The backbone of any toolkit, always in demand.', 'Iron_Ingot.webp', 25.00, 25.00, 5.00, 100.00, 0.6, '[2, 6]', '[30, 50, 20]', '["hold","hold","hold","hold","hold"]'),
    ('Copper', 'Slightly volatile. A versatile metal with unpredictable market swings.', 'Copper_Ingot.webp', 15.00, 15.00, 3.00, 75.00, 0.8, '[3, 7]', '[30, 45, 25]', '["hold","hold","hold","hold","hold"]'),
    ('Gold', 'Mid-tier, balanced. Prized for its lustre and consistent trading value.', 'Gold_Ingot.webp', 50.00, 50.00, 10.00, 200.00, 0.9, '[2, 7]', '[30, 45, 25]', '["hold","hold","hold","hold","hold"]'),
    ('Lapis Lazuli', 'Unpredictable. A mystical gem whose value shifts with the winds of fortune.', 'Lapis_Lazuli.webp', 30.00, 30.00, 5.00, 150.00, 1.0, '[3, 8]', '[28, 40, 32]', '["hold","hold","hold","hold","hold"]'),
    ('Redstone', 'High risk. Powers complex machinery but its market is notoriously unstable.', 'Redstone_Dust.webp', 20.00, 20.00, 3.00, 120.00, 1.2, '[4, 10]', '[25, 35, 40]', '["hold","hold","hold","hold","hold"]'),
    ('Emerald', 'Premium, moderate volatility. The currency of villagers, valued for its rarity.', 'Emerald.webp', 75.00, 75.00, 15.00, 300.00, 0.9, '[3, 7]', '[35, 40, 25]', '["hold","hold","hold","hold","hold"]'),
    ('Diamond', 'High value, relatively stable. The pinnacle of mining, coveted by all.', 'Diamond.webp', 100.00, 100.00, 20.00, 400.00, 0.7, '[2, 6]', '[35, 45, 20]', '["hold","hold","hold","hold","hold"]'),
    ('Netherite', 'Highest value, very volatile. Forged in the depths of the Nether, extremely rare.', 'Netherite_Ingot.webp', 150.00, 150.00, 25.00, 500.00, 1.4, '[5, 12]', '[25, 30, 45]', '["hold","hold","hold","hold","hold"]');
