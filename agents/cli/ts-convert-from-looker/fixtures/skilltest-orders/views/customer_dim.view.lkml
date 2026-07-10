view: customer_dim {
  sql_table_name: MY_DB.MY_SCHEMA.CUSTOMER_DIM ;;

  dimension: customer_key {
    primary_key: yes
    hidden: yes
    type: number
    sql: ${TABLE}.CUSTOMER_KEY ;;
  }

  dimension: region {
    type: string
    sql: ${TABLE}.REGION ;;
  }

  dimension: customer_segment {
    type: string
    sql: ${TABLE}.CUSTOMER_SEGMENT ;;
  }

  dimension: loyalty_tier {
    type: string
    sql: ${TABLE}.LOYALTY_TIER ;;
  }
}
