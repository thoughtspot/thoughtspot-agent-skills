view: order_fact {
  sql_table_name: MY_DB.MY_SCHEMA.ORDER_FACT ;;

  dimension: order_id {
    type: string
    sql: ${TABLE}.ORDER_ID ;;
  }

  dimension: customer_key {
    type: number
    hidden: yes
    sql: ${TABLE}.CUSTOMER_KEY ;;
  }

  dimension: net_revenue {
    type: number
    hidden: yes
    sql: ${TABLE}.NET_REVENUE ;;
  }

  measure: total_net_revenue {
    type: sum
    sql: ${net_revenue} ;;
    value_format_name: usd
  }

  measure: order_count {
    type: count_distinct
    sql: ${TABLE}.ORDER_ID ;;
  }

  measure: average_order_value {
    type: number
    sql: 1.0 * ${total_net_revenue} / NULLIF(${order_count}, 0) ;;
    value_format_name: usd
  }
}
