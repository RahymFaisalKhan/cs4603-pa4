CREATE OR REPLACE FUNCTION {catalog}.{schema}.to_billions(
    amount_yen DOUBLE COMMENT 'A monetary amount expressed in individual Japanese yen.'
)
RETURNS DOUBLE
LANGUAGE SQL
COMMENT 'Convert an amount in Japanese yen to billions of yen by dividing by 1,000,000,000.'
RETURN amount_yen / 1000000000.0
