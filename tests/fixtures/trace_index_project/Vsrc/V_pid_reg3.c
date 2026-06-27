#include "V_pid_reg3.h"

static inline int32_t _IQmpy(int32_t a, int32_t b)
{
        return (int32_t)(((int64_t)a * (int64_t)b) >> 6);
}

/* @covers LLR003: реализация абстрактной операции DeadZone из раздела 1.3 спецификации. */
static inline int32_t pid_apply_deadzone(int32_t error, int32_t deadzone)
{
        const int32_t zone = (deadzone > 0) ? deadzone : 0;

        if (zone == 0) {
                return error;
        }

        if (error > 0) {
                const int32_t reduced = error - zone;
                return (reduced > 0) ? reduced : 0;
        }

        if (error < 0) {
                const int32_t increased = error + zone;
                return (increased < 0) ? increased : 0;
        }

        return 0;
}

/* @covers LLR-004, LLR010: реализация абстрактной операции Clamp из раздела 1.3 спецификации. */
static inline int32_t pid_saturate(int32_t value, int32_t minimum, int32_t maximum)
{
        if (value > maximum) {
                return maximum;
        }
        if (value < minimum) {
                return minimum;
        }
        return value;
}

void pid_reg3_calc(TPidReg3 *v)
{
        /* @covers LLR-3, LLR-012: вычисление ошибки, учёт мёртвой зоны и безопасная разность входов. */
        v->e_reg3 = v->pid_ref_reg3 - v->pid_fdb_reg3;
        v->internal.e_reg3Dz = pid_apply_deadzone(v->e_reg3, v->DeadZone);

        /* @covers LLR-006: фильтр дифференциальной составляющей. */
        int32_t filtered_error;
        if (v->Kf_d == 0) {
                filtered_error = v->e_reg3;
        } else {
                const int32_t filtered_delta = _IQmpy(v->Kf_d,
                                (v->e_reg3 - v->e_reg3_filterOut));
                filtered_error = v->e_reg3_filterOut + filtered_delta;
        }

        /* @covers LLR005, LLR007: планировщик пересчёта дифференциала. */
        int32_t derivative = v->ud_reg3;
        int32_t previous_filter = v->internal.up1_reg3;
        const uint32_t diff_limit = (v->DiffDelim > 0) ? (uint32_t)v->DiffDelim : 0U;
        uint32_t diff_counter = 0U;

        if (v->internal.DiffCounter > 0) {
                diff_counter = (uint32_t)v->internal.DiffCounter;
        }

        if ((diff_limit == 0U) || ((diff_counter + 1U) >= diff_limit)) {
                if (v->internal.KdFilterInitFlag != 0) {
                        filtered_error = v->e_reg3;
                        previous_filter = filtered_error;
                        derivative = 0;
                        v->internal.KdFilterInitFlag = 0;
                } else {
                        const int32_t delta = filtered_error - previous_filter;
                        /* @covers LLR005, LLR-012: масштабирование разницы фильтра в пределах int32_t. */
                        const int32_t scaled_delta = (int32_t)((int64_t)delta * 64);
                        derivative = _IQmpy(v->Kd_reg3, scaled_delta);
                        previous_filter = filtered_error;
                }
                diff_counter = 0U;
        } else {
                diff_counter += 1U;
        }

        v->internal.DiffCounter = (int32_t)diff_counter;
        v->ud_reg3 = derivative;
        v->internal.up1_reg3 = previous_filter;
        v->e_reg3_filterOut = filtered_error;

        /* @covers LLR003, LLR-004: пропорциональная часть и сумма до насыщения. */
        v->up_reg3 = _IQmpy(v->Kp_reg3, v->internal.e_reg3Dz);

        int32_t integrator = v->ui_reg3;
        if (v->Ki_reg3 == 0) {
                integrator = 0;
        } else if (v->Kc_reg3 == 0) {
                integrator = pid_saturate(integrator, v->pid_out_min, v->pid_out_max);
        }

        int32_t uprsat_sum = v->up_reg3 + integrator;
        uprsat_sum = uprsat_sum + v->ud_reg3;
        v->internal.uprsat_reg3 = uprsat_sum;
        v->pid_out_reg3 = pid_saturate(v->internal.uprsat_reg3, v->pid_out_min, v->pid_out_max);

        /* @covers LLR-009: вычисление ошибки насыщения для анти-виндапа. */
        const int32_t saterr_diff = v->pid_out_reg3 - v->internal.uprsat_reg3;
        v->saterr_reg3 = saterr_diff + v->saterr_reg3Add;

        /* @covers LLR008, LLR-009: интегратор и анти-виндап. */
        if (v->Ki_reg3 != 0) {
                int32_t ui_next = v->ui_reg3;
                ui_next = ui_next + _IQmpy(v->Ki_reg3, v->up_reg3);
                ui_next = ui_next + _IQmpy(v->Kc_reg3, v->saterr_reg3);
                v->ui_reg3 = ui_next;
        } else {
                v->ui_reg3 = 0;
        }

        /* @covers LLR010: ограничение интегратора при отключённом анти-виндапе. */
        if (v->Kc_reg3 == 0) {
                v->ui_reg3 = pid_saturate(v->ui_reg3, v->pid_out_min, v->pid_out_max);
        }
}

void pid_reg3_reset(TPidReg3 *v)
{
        /* @covers LLR007, LLR011: полный сброс состояния экземпляра. */
        v->pid_ref_reg3 = 0;
        v->pid_fdb_reg3 = 0;
        v->e_reg3 = 0;
        v->up_reg3 = 0;
        v->ui_reg3 = 0;
        v->ud_reg3 = 0;
        v->internal.uprsat_reg3 = 0;
        v->pid_out_reg3 = 0;
        v->saterr_reg3 = 0;
        v->e_reg3_filterOut = 0;
        v->internal.up1_reg3 = 0;
        v->internal.DiffCounter = 0;
        v->internal.KdFilterInitFlag = 1;
        v->internal.e_reg3Dz = 0;
}
