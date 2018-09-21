import getpass
import json
from pathlib import Path
from .board import BoardLayout, create_nonces
from .client import BattleshipClient
import click
from click import ClickException


@click.group()
@click.option('-u', '--url', default='http://127.0.0.1:8008', help='The URL of the Sawtooth REST API.')
@click.option('-k', '--key-file', default=getpass.getuser(), help='The key file to use for sending transactions.')
@click.option('-w', '--wait', default=60, type=int, help='How long to wait for a transaction to complete.')
@click.pass_context
def cli(ctx, url, key_file, wait):
    if ctx.obj is None:
        ctx.obj = {}

    ctx.obj['URL'] = url
    ctx.obj['KEY_FILE'] = Path.home() / '.sawtooth' / 'keys' / f'{key_file}.priv'
    ctx.obj['WAIT'] = wait


@cli.command()
@click.pass_context
@click.argument('NAME')
@click.option('-s', '--ships', default=["AAAAA", "BBBB", "CCC", "DD", "DD", "SSS", "SSS"], help='The ships to use for this game.')
def create(ctx, name, ships):
    client = BattleshipClient(
        base_url=ctx.obj['URL'],
        keyfile=ctx.obj['KEY_FILE'],
        wait=ctx.obj['WAIT'],
    )

    client.create(name=name, ships=ships)


@cli.command()
@click.pass_context
def list(ctx):
    client = BattleshipClient(
        base_url=ctx.obj['URL'],
        keyfile=ctx.obj['KEY_FILE'],
        wait=ctx.obj['WAIT'],
    )
    games = client.list_games()

    fmt = "%-15s %-15.15s %-15.15s %s"

    print(fmt % ('GAME', 'PLAYER 1', 'PLAYER 2', 'STATE'))

    for game in sorted(games, key=lambda g: g['name']):
        print(fmt % (game['name'], game['Player1'] or '', game['Player2'] or '', game['State']))


@cli.command()
@click.pass_context
@click.argument('NAME')
def show(ctx, name):
    client = BattleshipClient(
        base_url=ctx.obj['URL'],
        keyfile=ctx.obj['KEY_FILE'],
        wait=ctx.obj['WAIT'],
    )
    games = client.list_games()

    try:
        game = next(game for game in games if name == game['name'])
    except StopIteration:
        raise ClickException('no such game: {}'.format(name))

    player1 = game['Player1']
    player2 = game['Player2']
    game_state = game['State']

    print("GAME:     : {}".format(name))
    print("PLAYER 1  : {}".format(player1))
    print("PLAYER 2  : {}".format(player2))
    print("STATE     : {}".format(game_state))

    # figure out the proper user's target board, given the public_key
    with open(Path(ctx.obj['KEY_FILE']).with_suffix('.pub')) as f:
        public_key = f.readline().rstrip('\n')

    if 'Player1' in game and public_key == game['Player1']:
        target_board_name = 'TargetBoard1'
    elif 'Player2' in game and public_key == game['Player2']:
        target_board_name = 'TargetBoard2'
    else:
        raise ClickException("Player hasn't joined game.")

    # figure out who fired last and who is calling do_show
    # to determine which board * is diplayed on to
    # show pending shot

    try:
        last_fire = (
            int(ord(game['LastFireRow'])) - ord('A'),
            int(game['LastFireColumn']) - 1,
        )
    except TypeError:
        last_fire = None

    if game_state == 'P1-NEXT' and target_board_name == 'TargetBoard1':
        # player 2 last shot and player 1 is looking
        will_be_on_target_board = False
    elif game_state == 'P1-NEXT' and target_board_name == 'TargetBoard2':
        # player 2 last shot and player 2 is looking
        will_be_on_target_board = True
    elif game_state == 'P2-NEXT' and target_board_name == 'TargetBoard1':
        # player 1 last shot and player 1 is looking
        will_be_on_target_board = True
    elif game_state == 'P2-NEXT' and target_board_name == 'TargetBoard2':
        # player 1 last shot and player 2 is looking
        will_be_on_target_board = False
    else:
        last_fire = None
        will_be_on_target_board = False

    if target_board_name in game:
        target_board = game[target_board_name]
        size = len(target_board)

        print()
        print("  Target Board")
        print_board(
            target_board,
            size,
            is_target_board=True,
            pending_on_target_board=will_be_on_target_board,
            last_fire=last_fire
        )

    data = get_board(name, Path(ctx.obj['KEY_FILE']).stem)

    if data:
        layout = BoardLayout.deserialize(data['spaces'])
        board = layout.render()
        size = len(board)

        print()
        print("  Secret Board")
        print_board(
            board,
            size,
            is_target_board=False,
            pending_on_target_board=will_be_on_target_board,
            last_fire=last_fire,
        )


@cli.command()
@click.pass_context
@click.argument('NAME')
def join(ctx, name):
    client = BattleshipClient(
        base_url=ctx.obj['URL'],
        keyfile=ctx.obj['KEY_FILE'],
        wait=ctx.obj['WAIT'],
    )
    games = client.list_games()

    try:
        game = next(game for game in games if name == game['name'])
    except StopIteration:
        raise ClickException('no such game: {}'.format(name))

    data = get_or_create_board(name, Path(ctx.obj['KEY_FILE']).stem, game['Ships'])

    layout = BoardLayout.deserialize(data['spaces'])

    hashed_board = layout.render_hashed(data['nonces'])

    client.join(name=name, board=hashed_board)


@cli.command()
@click.pass_context
@click.argument('NAME')
@click.argument('ROW')
@click.argument('COL')
def fire(ctx, name, row, col):
    client = BattleshipClient(
        base_url=ctx.obj['URL'],
        keyfile=ctx.obj['KEY_FILE'],
        wait=ctx.obj['WAIT'],
    )
    games = client.list_games()

    try:
        game = next(game for game in games if name == game['name'])
    except StopIteration:
        raise ClickException(f'No such game: {name}')

    data = get_board(name, Path(ctx.obj['KEY_FILE']).stem)

    if data is None:
        raise ClickException(f'No such game: {name}')

    reveal_space = None
    reveal_nonce = None

    if game['LastFireColumn'] is not None:
        last_row = ord(game['LastFireRow']) - ord('A')
        last_col = int(game['LastFireColumn']) - 1

        layout = BoardLayout.deserialize(data['spaces'])
        nonces = data['nonces']

        reveal_space = layout.render()[last_row][last_col]
        reveal_nonce = nonces[last_row][last_col]

    response = client.fire(
        name=name,
        column=col,
        row=row,
        reveal_space=reveal_space,
        reveal_nonce=reveal_nonce)

    print(response)


####################
# Helper Functions #
####################

def cli_wrapper():
    try:
        cli()
    except Exception as e:
        click.echo(e)
        import traceback
        traceback.print_exc()


def get_board(name, alias):
    path = Path.home() / '.sawtooth' / 'battleship' / f'{alias}-{name}.json'

    with open(path) as f:
        return json.load(f)


def get_or_create_board(name, alias, ships=None, create_if_nonexistent=True):
    path = Path.home() / '.sawtooth' / 'battleship' / f'{alias}-{name}.json'

    try:
        with open(path) as f:
            return json.load(f)
    except IOError:
        if create_if_nonexistent:
            if not ships:
                raise ValueError("Ships are required when creating a new layout!")
            new_layout = BoardLayout.generate(ships=ships)
            data = {
                'spaces': new_layout.serialize(),
                'nonces': create_nonces(new_layout.size)
            }

            with open(path, 'w') as f:
                json.dump(data, f, sort_keys=True, indent=4)

            return data
        else:
            return None


def print_board(board, size, is_target_board=True, pending_on_target_board=False, last_fire=None):
    print(''.join(["-"] * (size * 3 + 3)))
    print("  ", end=' ')
    for i in range(size):
        print(f" {i + 1}", end=' ')
    print()

    for row_idx, row in enumerate(range(0, size)):
        print("%s " % chr(ord('A') + row_idx), end=' ')
        for col_idx, space in enumerate(board[row]):
            if is_target_board:
                if pending_on_target_board and last_fire is not None and \
                        row_idx == last_fire[0] and col_idx == last_fire[1]:

                    print(" {}".format(space.replace('?', '*')), end=' ')
                else:
                    print(" {}".format(space.replace('?', ' ').replace('M', '.').replace('H', 'X')), end=' ')

            else:
                if not pending_on_target_board and last_fire is not None and \
                        row_idx == last_fire[0] and col_idx == last_fire[1]:
                    print(" {}".format(
                        '*'
                    ), end=' ')
                else:
                    print(" {}".format(
                        space.replace('-', ' ')
                    ), end=' ')
        print()


if __name__ == '__main__':
    cli()
