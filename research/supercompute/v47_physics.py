"""Numerical 2-D hard-sphere toy; all parameters are assumed, never measured."""
import copy
import math
import random


def step_system(balls, *, dt=.05, restitution=.85, friction=.04,
                drag=.08, airflow=(.08, .18)):
    """Semi-implicit Euler, mass-dependent drag, wall and pair impulses.

    Units are arbitrary simulation units. This is not a calibrated draw machine.
    Tangential contact impulse is Coulomb-limited; spin is not modelled.
    """
    scalars = (dt, restitution, friction, drag, *airflow)
    if (len(airflow) != 2 or not all(math.isfinite(x) for x in scalars)
            or not 0 < dt <= 1 or not 0 <= restitution <= 1
            or not 0 <= friction <= 1 or drag < 0):
        raise ValueError('invalid mechanics parameters')
    counts = {'pair_contacts': 0, 'pair_impulses': 0, 'wall_impulses': 0}
    for ball in balls:
        mass, radius = ball['mass'], ball['radius']
        if (not math.isfinite(mass) or mass <= 0 or not 0 < radius < .5
                or any(not math.isfinite(v) for v in ball['position']+ball['velocity'])):
            raise ValueError('invalid ball state')
        # Quadratic relative-air drag; acceleration is force divided by mass.
        relative = [airflow[d] - ball['velocity'][d] for d in (0, 1)]
        speed = math.hypot(*relative)
        ball['acceleration'] = [drag * speed * u / mass for u in relative]
        for d in (0, 1):
            ball['velocity'][d] += ball['acceleration'][d] * dt
            ball['position'][d] += ball['velocity'][d] * dt
    for i, a in enumerate(balls):
        for b in balls[i+1:]:
            delta = [b['position'][d]-a['position'][d] for d in (0,1)]
            distance = math.hypot(*delta)
            radius_sum = a['radius']+b['radius']
            if distance >= radius_sum:
                continue
            counts['pair_contacts'] += 1
            normal = [u/distance for u in delta] if distance > 1e-12 else [1.,0.]
            inv_a, inv_b = 1/a['mass'], 1/b['mass']
            inv_sum = inv_a+inv_b
            overlap = radius_sum-distance
            for d in (0,1):
                a['position'][d] -= overlap*normal[d]*inv_a/inv_sum
                b['position'][d] += overlap*normal[d]*inv_b/inv_sum
            closing = sum((a['velocity'][d]-b['velocity'][d])*normal[d] for d in (0,1))
            if closing <= 0:
                continue
            impulse = (1+restitution)*closing/inv_sum
            tangent = [-normal[1], normal[0]]
            slip = sum((a['velocity'][d]-b['velocity'][d])*tangent[d] for d in (0,1))
            tangential = max(-friction*impulse, min(friction*impulse, slip/inv_sum))
            for d in (0,1):
                change = impulse*normal[d]+tangential*tangent[d]
                a['velocity'][d] -= change*inv_a
                b['velocity'][d] += change*inv_b
            counts['pair_impulses'] += 1
    for ball in balls:
        radius = ball['radius']
        for d in (0,1):
            coordinate, velocity = ball['position'][d], ball['velocity'][d]
            if coordinate < radius or coordinate > 1-radius:
                ball['position'][d] = max(radius, min(1-radius, coordinate))
                if (coordinate < radius and velocity < 0) or (coordinate > 1-radius and velocity > 0):
                    ball['velocity'][d] *= -restitution
                    ball['velocity'][1-d] *= 1-friction
                    counts['wall_impulses'] += 1
    return counts


def simulate_area(maximum, picked, seed, steps, *, dt=.05, restitution=.85,
                  friction=.04, drag=.08, airflow=(.08,.18), mass=1., radius=.025):
    if type(steps) is not int or not 1 <= steps <= 1000 or mass <= 0 or not 0 < radius < .06:
        raise ValueError('invalid simulation bounds')
    rng = random.Random(seed)
    balls = []
    for number in range(1, maximum+1):
        for _ in range(10000):
            position = [rng.uniform(radius,1-radius) for _ in (0,1)]
            if all(math.dist(position, b['position']) > 2*radius for b in balls):
                break
        else:
            raise ValueError('cannot initialize non-overlapping balls')
        balls.append({'number':number, 'mass':mass, 'radius':radius,
                      'position':position, 'velocity':[rng.uniform(-.45,.45) for _ in (0,1)],
                      'acceleration':[0.,0.]})
    trajectory = [{'step':0, 'time':0., 'balls':copy.deepcopy(balls)}]
    counts = {'pair_contacts':0,'pair_impulses':0,'wall_impulses':0}
    for step in range(1, steps+1):
        events = step_system(balls, dt=dt, restitution=restitution, friction=friction,
                             drag=drag, airflow=airflow)
        for key, value in events.items():
            counts[key] += value
        if step % max(1, steps//8) == 0 or step == steps:
            trajectory.append({'step':step,'time':step*dt,'balls':copy.deepcopy(balls)})
    # Explicit toy extraction aperture: rank by distance to the top-centre outlet.
    order = sorted(balls, key=lambda b:(math.dist(b['position'], [.5,1.]),b['number']))
    return {'ticket':sorted(b['number'] for b in order[:picked]),
            'outlet':[.5,1.], 'selection':'nearest_final_position_to_outlet',
            'final_balls':balls, 'trajectory':trajectory, **counts,
            'parameters':dict(dt=dt,restitution=restitution,friction=friction,
                              drag=drag,airflow=list(airflow),mass=mass,radius=radius)}
