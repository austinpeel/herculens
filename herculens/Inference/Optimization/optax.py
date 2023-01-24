# Handles different method to optimize a loss function
# 
# Copyright (c) 2021, herculens developers and contributors

__author__ = 'aymgal', 'austinpeel'


import time
import numpy as np
import jax
import optax

from herculens.Inference.Optimization.base_optim import BaseOptimizer


__all__ = ['OptaxOptimizer']


class OptaxOptimizer(BaseOptimizer):
    """Wrapper to optax's gradient descent optimizers"""

    def run(self, init_params, algorithm='adabelief', max_iterations=100, min_iterations=None,
              init_learning_rate=1e-2, schedule_learning_rate=True, 
              stop_at_loss_increase=False, progress_bar=True, return_param_history=False):
        if min_iterations is None:
            min_iterations = max_iterations
        if schedule_learning_rate is True:
            # Exponential decay of the learning rate
            scheduler = optax.exponential_decay(
                init_value=init_learning_rate, 
                decay_rate=0.99, # TODO: this has never been fine-tuned (taken from optax examples)
                transition_steps=max_iterations)

            if algorithm.lower() == 'adabelief':
                scale_algo = optax.scale_by_belief()
            elif algorithm.lower() == 'radam':
                scale_algo = optax.scale_by_radam()
            elif algorithm.lower() == 'adam':
                scale_algo = optax.scale_by_adam()
            else:
                raise ValueError(f"Optax algorithm '{algorithm}' is not supported")

            # Combining gradient transforms using `optax.chain`
            optim = optax.chain(
                #optax.clip_by_global_norm(1.0),  # clip by the gradient by the global norm # TODO: what is this used for?
                scale_algo,  # use the updates from the chosen optimizer
                optax.scale_by_schedule(scheduler),  # Use the learning rate from the scheduler
                optax.scale(-1.)  # because gradient *descent*
            )
        else:
            if algorithm.lower() == 'adabelief':
                optim = optax.adabelief(init_learning_rate)
            elif algorithm.lower() == 'radam':
                optim = optax.radam(init_learning_rate)
            elif algorithm.lower() == 'adam':
                optim = optax.adam(init_learning_rate)
            else:
                raise ValueError(f"Optax algorithm '{algorithm}' is not supported")

        # Initialise optimizer state
        #params = self._param.current_values(as_kwargs=False, restart=restart_from_init, copy=True)
        params = init_params
        opt_state = optim.init(params)
        prev_params, prev_loss_val = params, 1e10

        @jax.jit
        def gd_step(params, opt_state):
            loss_val, grads = self.function_optim_with_grad(params)
            updates, opt_state = optim.update(grads, opt_state, params)
            params = optax.apply_updates(params, updates)
            return params, opt_state, loss_val

        # Gradient descent loop
        param_history = []
        loss_history = []
        start_time = time.time()
        for i in self._for_loop(range(max_iterations), progress_bar, 
                                total=max_iterations, 
                                desc=f"optax.{algorithm}"):
            params, opt_state, loss_val = gd_step(params, opt_state)
            if stop_at_loss_increase and i > min_iterations and loss > prev_loss:
                params, loss_val = prev_params, prev_loss_val
                break
            else:
                loss_history.append(loss_val)  # TODO: use jax.value_and_grad instead? but does it jit the gradient??
                prev_params, prev_loss_val = params, loss_val
            if return_param_history is True:
                param_history.append(params)
        runtime = time.time() - start_time
        best_fit = params
        logL_best_fit = self.loss.function(best_fit)
        extra_fields = {'loss_history': np.array(loss_history)}  # TODO: use optax.second_order module to compute diagonal of Hessian?
        if return_param_history is True:
            extra_fields['param_history'] = param_history
        return best_fit, logL_best_fit, extra_fields, runtime
