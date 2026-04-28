-- =========================================================
-- 1. analysis_task_type
-- =========================================================
create table if not exists analysis_task_type (
    task_type smallint primary key,
    task_name varchar(100) not null unique,
    task_desc text,
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

comment on table analysis_task_type is 'analysis task type definition';
comment on column analysis_task_type.task_type is 'analysis task type(code)';
comment on column analysis_task_type.task_name is 'analysis task type name';
comment on column analysis_task_type.task_desc is 'description of task';
comment on column analysis_task_type.is_active is 'active flag';


-- =========================================================
-- 2. analysis_result
-- =========================================================
create table if not exists analysis_result (
    result_id bigint primary key,
    task_type smallint not null,
    target_type varchar(20) not null,
    target_id text null,
    time_from timestamptz not null,
    time_to timestamptz not null,
    created_at timestamptz not null default now(),

    constraint fk_analysis_result_task_type
        foreign key (task_type)
        references analysis_task_type(task_type),

    constraint fk_analysis_result_target_id
        foreign key (target_id)
        references instances_raw(id),

    constraint chk_analysis_result_target_type
        check (target_type in ('instance', 'global')),

    -- constraint chk_analysis_result_target_id_by_type
    --     check (
    --         (target_type = 'instance' and target_id is not null)
    --         or
    --         (target_type = 'global' and target_id is null)
    --     ),

    constraint chk_analysis_result_time_range
        check (time_from <= time_to)
);

comment on table analysis_result is 'meta info of analysis result';
comment on column analysis_result.result_id is 'analysis result id';
comment on column analysis_result.task_type is 'task type of analysis';
comment on column analysis_result.target_type is 'analysis target type:[instance/global]';
comment on column analysis_result.target_id is 'for type "instance", refers to instances_raw.id, otherwise null';
comment on column analysis_result.time_from is 'from-time';
comment on column analysis_result.time_to is 'to-time';
comment on column analysis_result.created_at is 'executed time of analysis';


-- =========================================================
-- 3. res_timeseries
--    for timeseries analysis, store x->y values to this table
--    it can provide time values by scale type d(ay)/w(eek)/m(onth)/y(ear) per 1 result_id : x_scale_type
-- =========================================================
create table if not exists res_timeseries (
    result_id bigint not null,
    x_scale_type char(1) not null,
    x_order integer not null,
    x_value timestamptz not null,
    y_value numeric(20,4) not null,

    constraint pk_res_timeseries
        primary key (result_id, x_scale_type, x_order),

    constraint fk_res_timeseries_result_id
        foreign key (result_id)
        references analysis_result(result_id)
        on delete cascade,

    constraint chk_res_timeseries_x_scale_type
        check (x_scale_type in ('d', 'w', 'm', 'y')),

    constraint chk_res_timeseries_x_order
        check (x_order >= 0)
);

comment on table res_timeseries is 'timeseries values for analysis result';
comment on column res_timeseries.result_id is 'analysis result_id';
comment on column res_timeseries.x_scale_type is 'scale unit: d(ay)/w(eek)/m(onth)/y(ear)';
comment on column res_timeseries.x_order is 'order of x-axis values';
comment on column res_timeseries.x_value is 'real value of x-axis (time)';
comment on column res_timeseries.y_value is 'real y value';


-- =========================================================
-- 4. res_rank
-- =========================================================
create table if not exists res_rank (
    result_id bigint not null,
    rank_value integer not null,
    label varchar(255) not null,
    instance_id text null,
    amount numeric(20,4) not null,
    metric_type varchar(50) not null,
    extra_json jsonb,

    constraint pk_res_rank
        primary key (result_id, metric_type, rank_value, label),

    constraint fk_res_rank_result_id
        foreign key (result_id)
        references analysis_result(result_id)
        on delete cascade,

    constraint fk_res_rank_instance_id
        foreign key (instance_id)
        references instances_raw(id),

    constraint chk_res_rank_rank_value
        check (rank_value >= 1)
);

comment on table res_rank is 'rank analysis result(for trend & instance analysis)';
comment on column res_rank.result_id is 'analysis result_id';
comment on column res_rank.rank_value is 'rank';
comment on column res_rank.label is 'label to view (hashtag/instance ...)';
comment on column res_rank.instance_id is 'target instance id';
comment on column res_rank.amount is 'metric value of the rank';
comment on column res_rank.metric_type is 'metric name';
comment on column res_rank.extra_json is 'extra info (json)';


-- =========================================================
-- 5. res_instance
-- =========================================================
create table if not exists res_instance (
    result_id bigint not null,
    instance_id text not null,
    user_count bigint,
    activity numeric(20,6),
    trend_activity numeric(20,6),
    posts_per_day numeric(20,6),

    constraint pk_res_instance
        primary key (result_id, instance_id),

    constraint fk_res_instance_result_id
        foreign key (result_id)
        references analysis_result(result_id)
        on delete cascade,

    constraint fk_res_instance_instance_id
        foreign key (instance_id)
        references instances_raw(id),

    constraint chk_res_instance_user_count
        check (user_count is null or user_count >= 0),

    constraint chk_res_instance_activity
        check (activity is null or activity >= 0),

    constraint chk_res_instance_trend_activity
        check (trend_activity is null or trend_activity >= 0),

    constraint chk_res_instance_posts_per_day
        check (posts_per_day is null or posts_per_day >= 0)
);

comment on table res_instance is 'instance analysis result info';
comment on column res_instance.result_id is 'analysis result id';
comment on column res_instance.instance_id is 'target instance id';
comment on column res_instance.user_count is 'user_count (of period)';
comment on column res_instance.activity is 'avg activity(user/active_user)';
comment on column res_instance.trend_activity is 'avg trend activity(uses/accounts)';
comment on column res_instance.posts_per_day is 'posts per day';


-- =========================================================
-- 6. current_analysis_result
--    representative analysis result
-- =========================================================
create table if not exists current_analysis_result (
    task_type smallint not null,
    target_type varchar(20) not null,
    result_id bigint not null,
    target_id text null,
    created_at timestamptz not null default now(),

    constraint fk_current_analysis_result_task_type
        foreign key (task_type)
        references analysis_task_type(task_type),

    constraint fk_current_analysis_result_result_id
        foreign key (result_id)
        references analysis_result(result_id)
        on delete cascade,

    constraint fk_current_analysis_result_target_id
        foreign key (target_id)
        references instances_raw(id),

    constraint chk_current_analysis_result_target_type
        check (target_type in ('instance', 'global')),

    constraint chk_current_analysis_result_target_id_by_type
        check (
            (target_type = 'instance' and target_id is not null)
            or
            (target_type = 'global' and target_id is null)
        )
);

comment on table current_analysis_result is 'representative analysis result (for frontend)';
comment on column current_analysis_result.task_type is 'task type';
comment on column current_analysis_result.target_type is 'target type: instance/global';
comment on column current_analysis_result.result_id is 'current result_id';
comment on column current_analysis_result.target_id is 'target instance_id (refers to instance_raw.id/for instance type only)';
comment on column current_analysis_result.created_at is 'created time';


-- global: unique by task_type
create unique index if not exists uq_current_analysis_result_global
    on current_analysis_result (task_type, target_type)
    where target_type = 'global';

-- instance: unique by task_type + target_id
create unique index if not exists uq_current_analysis_result_instance
    on current_analysis_result (task_type, target_type, target_id)
    where target_type = 'instance';


-- =========================================================
-- 7. indexes
-- =========================================================
create index if not exists idx_analysis_result_task_type
    on analysis_result(task_type);

create index if not exists idx_analysis_result_target
    on analysis_result(target_type, target_id);

create index if not exists idx_analysis_result_created_at
    on analysis_result(created_at desc);

create index if not exists idx_analysis_result_time_range
    on analysis_result(time_from, time_to);

create index if not exists idx_res_timeseries_result_scale
    on res_timeseries(result_id, x_scale_type, x_order);

create index if not exists idx_res_timeseries_x_value
    on res_timeseries(x_value);

create index if not exists idx_res_rank_result_id
    on res_rank(result_id);

create index if not exists idx_res_rank_instance_id
    on res_rank(instance_id);

create index if not exists idx_res_rank_metric_type
    on res_rank(metric_type);

create index if not exists idx_res_instance_result_id
    on res_instance(result_id);

create index if not exists idx_res_instance_instance_id
    on res_instance(instance_id);

create index if not exists idx_current_analysis_result_result_id
    on current_analysis_result(result_id);
